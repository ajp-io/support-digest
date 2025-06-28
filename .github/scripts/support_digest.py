import os, json, datetime, textwrap, time
import concurrent.futures
from zoneinfo import ZoneInfo
from github import Github
from slack_sdk.webhook import WebhookClient
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file for local development
load_dotenv()

ORG   = "replicated-collab"

# Product configuration - single source of truth
PRODUCTS = {
    "product::embedded-cluster": "Embedded Cluster",
    "product::kots": "KOTS", 
    "product::kurl": "kURL"
}

# East Coast timezone
EAST_COAST_TZ = ZoneInfo("America/New_York")


def fetch_issue_data(issue, since, product_label):
    """Fetch all data for a single issue (comments, metadata)"""
    # ------- always‑included static context -------
    meta = {
        "title": issue.title,
        "number": issue.number,
        "repo": issue.repository.name,
        "labels": [l.name for l in issue.labels],
        "body": (issue.body or ""),
        "url": issue.html_url,
        "created_at": issue.created_at.isoformat(),
        "updated_at": issue.updated_at.isoformat(),
        "state": issue.state,
        "product_label": product_label,
    }

    # ------- dynamic events -------
    events = []
    
    # Check for new comments in the time window
    try:
        for c in issue.get_comments(since):
            events.append({
                "type": "comment",
                "author": c.user.login,
                "body": c.body,
                "created_at": c.created_at.isoformat(),
            })
    except Exception as e:
        print(f"[ERROR] Failed to fetch comments for {issue.repository.name}#{issue.number}: {e}")
        # Continue with empty events rather than failing completely

    # Check if issue was created within the time window
    issue_created_in_window = issue.created_at >= since
    
    # Include issues that either:
    # 1. Were created within the time window (newly opened issues)
    # 2. Have events (comments) in the time window
    if issue_created_in_window or events:
        if issue_created_in_window:
            print(f"[DEBUG] Including issue {issue.repository.name}#{issue.number} - newly created in time window")
        else:
            print(f"[DEBUG] Including issue {issue.repository.name}#{issue.number} - has comments")
        return {**meta, "events": events}
    else:
        print(f"[DEBUG] Issue {issue.repository.name}#{issue.number} has no events in time window and was not created in time window")
        return None


def gather_deltas(gh, since, product_label):
    print(f"[DEBUG] Gathering deltas since {since.isoformat()}")
    print(f"[DEBUG] Processing product: {product_label}")
    
    print(f"[DEBUG] Checking issues with label: {product_label}")
    query = f'is:issue label:"{product_label}" label:"kind::inbound-escalation" org:{ORG} updated:>{since.isoformat()}'
    issues = gh.search_issues(query, sort="updated", order="asc")
    
    # Convert generator to list to get total count
    issues_list = list(issues)
    print(f"[DEBUG] Found {len(issues_list)} issues to process for {product_label}")
    
    if not issues_list:
        return []
    
    # Process issues in parallel
    deltas = []
    max_workers = min(10, len(issues_list))  # Cap at 10 workers or number of issues
    
    print(f"[DEBUG] Processing {len(issues_list)} issues with {max_workers} workers...")
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all issue processing tasks
        future_to_issue = {
            executor.submit(fetch_issue_data, issue, since, product_label): issue 
            for issue in issues_list
        }
        
        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_issue):
            issue = future_to_issue[future]
            try:
                result = future.result()
                if result is not None:
                    deltas.append(result)
                    print(f"[DEBUG] ✓ Completed {issue.repository.name}#{issue.number}")
            except Exception as e:
                print(f"[ERROR] Failed to process {issue.repository.name}#{issue.number}: {e}")
    
    elapsed = time.time() - start_time
    print(f"[DEBUG] Completed processing {len(deltas)}/{len(issues_list)} issues in {elapsed:.1f}s")
    
    return deltas


def categorize_issues(deltas, since):
    """
    Simple categorization:
    1. Closed - Issue is currently closed
    2. Newly Opened - Created in time window (and not closed)
    3. Updated - Has meaningful activity in time window (and not closed, not newly opened)
    4. Skip - Everything else
    """
    closed = []
    newly_opened = []
    updated = []
    skipped_count = 0
    
    for delta in deltas:
        # Filter out issues that only have bot comments
        if not has_meaningful_activity(delta) and not delta.get("created_at") >= since.isoformat():
            print(f"[DEBUG] {delta['repo']}#{delta['number']} → SKIPPED (only bot comments)")
            skipped_count += 1
            continue
            
        if delta.get("state") == "closed":
            closed.append(delta)
            print(f"[DEBUG] {delta['repo']}#{delta['number']} → CLOSED")
        elif delta.get("created_at") >= since.isoformat():
            newly_opened.append(delta)
            print(f"[DEBUG] {delta['repo']}#{delta['number']} → NEWLY OPENED")
        elif has_meaningful_activity(delta):
            updated.append(delta)
            print(f"[DEBUG] {delta['repo']}#{delta['number']} → UPDATED")
    
    print(f"[DEBUG] Categorization: {len(newly_opened)} new, {len(updated)} updated, {len(closed)} closed, {skipped_count} skipped")
    return newly_opened, updated, closed


def has_meaningful_activity(delta):
    """Check if issue has non-bot comments"""
    for event in delta.get("events", []):
        if event.get("type") == "comment":
            if event.get("author") != "github-actions[bot]":
                return True
    return False


def summarize_issue(issue, issue_category):
    """Summarize an issue for its section"""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    
    content = json.dumps({
        "issue": issue,
        "issue_category": issue_category
    }, ensure_ascii=False)
    
    prompt = f"""
    You are a support-engineering assistant summarizing a GitHub issues for a Slack digest.

    Input payload (JSON, provided as the user message):
      • `issue`  - metadata & full body text
      • `events` - ONLY comments / label or assignee changes that occurred inside the time-window
      • `issue_category` - one of "newly_opened", "updated", or "closed"

    General output rules
    --------------------
    • Produce ONE Slack-formatted bullet:
          • <URL|repo#number> · *title* — <summary>
    • Use concise, active-voice fragments; ignore bot noise.
    • Be as detailed as needed—no token limit worries.
    • Quote logs/errors in ``` blocks when helpful.

    Checklist for **ALL** issues
    ----------------------------
    - **One-sentence problem statement**
    - Minimal repro steps (if present)
    - Key log line / error snippet (``` … ```)
    - Any workaround tried or suggested
    - Suspected root cause or product gap
    - Customer replies or expectations set
    - Notes from any support calls that occurred

    Additional items by **issue_category**
    ------------------------------------
    ★ newly_opened
      - Customer / tenant & severity (Sev-1/2/3)
      - Environment (product & version, OS/K8s, etc.)

    ★ updated
      - What changed in this window (new comments, labels, PR links)
      - Decisions made or config changes applied
      - Progress state (e.g. needs a support bundle, waiting on customer reply, etc.)
      - New blockers or unanswered questions—flag clearly
      - Severity / priority changes

    ★ closed
      - Resolution type (fix, docs change, won't-fix, duplicate, etc.)
      - Confirmed root cause (one sentence)
      - Details on any workarounds tried or suggested
      - Who verified and how (customer confirmed, CI, etc.)
      - PR / commit link that closed it
      - Follow-up tickets or backports opened
      - Docs / KB updates
      - Total time-to-resolution (hours / days open)

    Example (Slack Markdown)
    ------------------------
    • <https://github.com/replicated-collab/progress-replicated/issues/123|embedded-cluster#123> · *Cannot install on SELinux-enabled RHEL 9.3* — Sev-2 for AcmeCo. RHEL 9.3, Embedded Cluster v1.8.0. Preflight `selinux_config` fails with `permission denied`. Repro: fresh node, SELinux=enforcing, run install. No workaround yet. Suspect container-runtime policy gap. Owner: @alex-smith.

    (For **updated** and **closed** issues, swap in the relevant checklist items above.)
"""
    
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": content},
            ],
            max_tokens=1000,
            timeout=30,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERROR] Failed to summarize {issue['repo']}#{issue['number']}: {e}")
        return f"• <{issue['url']}|{issue['repo']}#{issue['number']}> · *{issue['title']}* — [Summarization failed]"


def process_issues_parallel(issues, issue_category, max_workers=10):
    """Process multiple issues in parallel"""
    if not issues:
        return []
    
    print(f"[DEBUG] Processing {len(issues)} {issue_category} issues in parallel...")
    start_time = time.time()
    
    summaries = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_issue = {
            executor.submit(summarize_issue, issue, issue_category): issue 
            for issue in issues
        }
        
        for future in concurrent.futures.as_completed(future_to_issue):
            issue = future_to_issue[future]
            try:
                summary = future.result()
                if summary:
                    summaries.append(summary)
                    print(f"[DEBUG] ✓ Completed {issue['repo']}#{issue['number']}")
            except Exception as e:
                print(f"[ERROR] Failed to process {issue['repo']}#{issue['number']}: {e}")
    
    elapsed = time.time() - start_time
    print(f"[DEBUG] Completed {len(summaries)}/{len(issues)} {issue_category} issues in {elapsed:.1f}s")
    
    return summaries


def build_digest(newly_opened, updated, closed):
    """Build the complete digest from categorized issues"""
    sections = []
    
    if newly_opened:
        new_summaries = process_issues_parallel(newly_opened, "newly_opened")
        if new_summaries:
            sections.append(f"*Newly Opened Issues*\n" + "\n".join(new_summaries))
    
    if updated:
        updated_summaries = process_issues_parallel(updated, "updated")
        if updated_summaries:
            sections.append(f"*Updated Issues*\n" + "\n".join(updated_summaries))
    
    if closed:
        closed_summaries = process_issues_parallel(closed, "closed")
        if closed_summaries:
            sections.append(f"*Closed Issues*\n" + "\n".join(closed_summaries))
    
    return "\n\n".join(sections)


def format_header(since, hours_back, product_label=None):
    """Format the digest header"""
    # Format the time window description
    if hours_back == 24:
        time_desc = "past 24h"
    elif hours_back < 24:
        time_desc = f"past {hours_back}h"
    else:
        days = hours_back // 24
        remaining_hours = hours_back % 24
        if remaining_hours == 0:
            time_desc = f"past {days}d"
        else:
            time_desc = f"past {days}d {remaining_hours}h"
    
    # Convert UTC time to East Coast time for display
    since_east_coast = since.astimezone(EAST_COAST_TZ)
    
    # Determine product name for the header
    product_name = PRODUCTS.get(product_label, "Unknown")
    header = (
        f"*{product_name} Support Digest* "
        f"({time_desc} – since {since_east_coast:%Y-%m-%d %H:%M ET})"
    )
    return header


def summarize(deltas, since, hours_back, product_label=None):
    """New summarize function using categorization and parallel processing"""
    print(f"[DEBUG] Summarizing deltas ({len(deltas)} issues)")
    
    # Categorize issues using simple Python logic
    newly_opened, updated, closed = categorize_issues(deltas, since)
    
    # Build digest with parallel processing
    summary = build_digest(newly_opened, updated, closed)
    
    # Format header
    header = format_header(since, hours_back, product_label)
    
    return f"{header}\n\n{summary}"


def run_for_product(product_label):
    """Run the support digest for a single product"""
    print(f"[DEBUG] Starting support digest script for {product_label}")
    
    # Get configurable time window (default 24 hours)
    hours_back = int(os.environ.get("HOURS_BACK", "24"))
    print(f"[DEBUG] Looking back {hours_back} hours")
    
    gh    = Github(os.environ["GH_TOKEN"])
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_back)
    deltas = gather_deltas(gh, since, product_label)

    if deltas:
        text = summarize(deltas, since, hours_back, product_label)
        print(f"[DEBUG] Sending to Slack: {text[:1000]}...")
        
        # Check for dry run mode
        if os.environ.get("DRY_RUN"):
            print("DRY RUN MODE - Not sending to Slack")
            print(f"Summary:\n{text}")
        else:
            resp = WebhookClient(os.environ["SLACK_WEBHOOK_URL"]).send(text=text)
            print(f"[DEBUG] Slack response: {resp.status_code} {resp.body}")
    else:
        print(f"[DEBUG] No deltas to report for {product_label}.")


def main():
    print("[DEBUG] Starting support digest script")
    
    # Check if a specific product is requested
    product_label = os.environ.get("PRODUCT_LABEL")
    
    if product_label:
        # Run for a single product
        run_for_product(product_label)
    else:
        # Run for all products separately
        print("[DEBUG] Running support digest for all products separately")
        for label in PRODUCTS:
            print(f"\n[DEBUG] ===== Processing {label} =====")
            run_for_product(label)
            print(f"[DEBUG] ===== Completed {label} =====\n")


if __name__ == "__main__":
    main()
