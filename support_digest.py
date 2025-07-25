import os, json, datetime, textwrap, time, sys
import concurrent.futures
from zoneinfo import ZoneInfo
from github import Github
from slack_sdk.webhook import WebhookClient
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file for local development
# This will be called later to avoid conflicts with team-specific environments

def load_config(config_path="config.installers.json"):
    """Load configuration from JSON file"""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] Configuration file {config_path} not found")
        return None
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in configuration file: {e}")
        return None

def get_config_path():
    """Get config file path from environment variable or default"""
    return os.environ.get("CONFIG_FILE", "config.installers.json")

def get_config():
    """Get configuration with fallback to environment variables"""
    config_path = get_config_path()
    config = load_config(config_path)
    if not config:
        # Fallback to original hardcoded values
        print("[WARNING] Using fallback configuration")
        return {
            "organizations": {
                "replicated-collab": {
                    "name": "Replicated Collab",
                    "products": {
                        "product::embedded-cluster": {
                            "name": "Embedded Cluster",
                            "display_name": "Embedded Cluster",
                            "github_org": "replicated-collab",
                            "issue_labels": ["kind::inbound-escalation"]
                        },
                        "product::kots": {
                            "name": "KOTS", 
                            "display_name": "KOTS",
                            "github_org": "replicated-collab",
                            "issue_labels": ["kind::inbound-escalation"]
                        },
                        "product::kurl": {
                            "name": "kURL",
                            "display_name": "kURL", 
                            "github_org": "replicated-collab",
                            "issue_labels": ["kind::inbound-escalation"]
                        }
                    }
                }
            },
            "defaults": {
                "hours_back": 24,
                "timezone": "America/New_York",
                "max_workers": 10,
                "openai_model": "gpt-4o-mini",
                "max_tokens": 1000
            }
        }
    return config

def get_product_config(product_label):
    """Get configuration for a specific product"""
    config = get_config()
    
    # Find the product in any organization
    for org_name, org_config in config["organizations"].items():
        if product_label in org_config.get("products", {}):
            product_config = org_config["products"][product_label]
            return {
                "org_name": org_name,
                "org_config": org_config,
                "product_config": product_config
            }
    
    return None

def get_all_products():
    """Get all product labels from configuration"""
    config = get_config()
    products = []
    
    for org_name, org_config in config["organizations"].items():
        for product_label in org_config.get("products", {}):
            products.append(product_label)
    
    return products

def get_timezone():
    """Get timezone from configuration"""
    config = get_config()
    tz_name = config.get("defaults", {}).get("timezone", "America/New_York")
    return ZoneInfo(tz_name)

def get_default_hours_back():
    """Get default hours back from configuration"""
    config = get_config()
    return config.get("defaults", {}).get("hours_back", 24)

def get_max_workers():
    """Get max workers from configuration"""
    config = get_config()
    return config.get("defaults", {}).get("max_workers", 10)

def get_openai_model():
    """Get OpenAI model from configuration"""
    config = get_config()
    return config.get("defaults", {}).get("openai_model", "gpt-4o-mini")

def get_max_tokens():
    """Get max tokens from configuration"""
    config = get_config()
    return config.get("defaults", {}).get("max_tokens", 1000)

def gather_deltas(gh, since, product_label):
    print(f"[DEBUG] Gathering deltas since {since.isoformat()}")
    print(f"[DEBUG] Processing product: {product_label}")
    
    # Get product configuration
    product_info = get_product_config(product_label)
    if not product_info:
        print(f"[ERROR] Product {product_label} not found in configuration")
        return []
    
    org_name = product_info["org_name"]
    org_config = product_info["org_config"]
    product_config = product_info["product_config"]
    additional_labels = product_config.get("issue_labels", [])
    
    # Get excluded repositories
    excluded_repos = org_config.get("excluded_repos", [])
    if excluded_repos:
        print(f"[DEBUG] Excluding repositories: {excluded_repos}")
    
    # Always include the product-specific label (from the config key)
    all_labels = [product_label] + additional_labels
    
    # Build query with all required labels
    label_queries = [f'label:"{label}"' for label in all_labels]
    label_query = ' '.join(label_queries)
    
    print(f"[DEBUG] Checking issues with labels: {all_labels}")
    
    # Use more precise GitHub search to reduce false positives
    # Search for issues created OR updated in the time window
    created_query = f'is:issue {label_query} org:{org_name} created:>{since.isoformat()}'
    updated_query = f'is:issue {label_query} org:{org_name} updated:>{since.isoformat()}'
    
    # Get both newly created and recently updated issues
    created_issues = list(gh.search_issues(created_query, sort="created", order="desc"))
    updated_issues = list(gh.search_issues(updated_query, sort="updated", order="desc"))
    
    # Combine and deduplicate issues, filtering out excluded repositories
    all_issues = {}
    for issue in created_issues + updated_issues:
        repo_name = issue.repository.name
        if repo_name not in excluded_repos:
            all_issues[f"{repo_name}#{issue.number}"] = issue
        else:
            print(f"[DEBUG] Skipping excluded repository: {repo_name}")
    
    issues_list = list(all_issues.values())
    print(f"[DEBUG] Found {len(issues_list)} candidate issues for {product_label} (after excluding {len(excluded_repos)} repositories)")
    
    if not issues_list:
        return []
    
    # Process issues in parallel with consolidated filtering
    deltas = []
    max_workers = min(get_max_workers(), len(issues_list))
    
    print(f"[DEBUG] Processing {len(issues_list)} issues with {max_workers} workers...")
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all issue processing tasks
        future_to_issue = {
            executor.submit(process_issue_with_filtering, issue, since, product_label): issue 
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

def process_issue_with_filtering(issue, since, product_label):
    """Process a single issue with consolidated filtering logic"""
    # GitHub API already filtered by time window, so we can trust the timestamps
    issue_created_in_window = issue.created_at >= since
    issue_updated_in_window = issue.updated_at >= since
    
    # Fetch issue metadata
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
    
    # Only fetch comments if we need them (issue was updated or we need to check for recent activity)
    all_comments = []
    has_recent_activity = False
    
    if issue_updated_in_window:
        try:
            comments = issue.get_comments()
            for c in comments:
                is_recent_activity = c.created_at >= since
                if is_recent_activity:
                    has_recent_activity = True
                
                all_comments.append({
                    "type": "comment",
                    "author": c.user.login,
                    "body": c.body,
                    "created_at": c.created_at.isoformat(),
                    "is_recent_activity": is_recent_activity,
                })
        except Exception as e:
            print(f"[ERROR] Failed to fetch comments for {issue.repository.name}#{issue.number}: {e}")
    
    # Apply filtering logic
    if issue_created_in_window:
        # Newly created issues are always included
        print(f"[DEBUG] Including {issue.repository.name}#{issue.number} - newly created")
        return {**meta, "comments": all_comments}
    elif has_recent_activity and has_meaningful_activity_from_comments(all_comments):
        # Updated issues with meaningful recent activity
        print(f"[DEBUG] Including {issue.repository.name}#{issue.number} - has meaningful recent activity")
        return {**meta, "comments": all_comments}
    else:
        # Filter out issues with only bot activity or no recent activity
        print(f"[DEBUG] Skipping {issue.repository.name}#{issue.number} - no meaningful recent activity")
        return None

def has_meaningful_activity_from_comments(comments):
    """Check if comments contain meaningful (non-bot) recent activity"""
    for comment in comments:
        if comment.get("is_recent_activity") and comment.get("author") != "github-actions[bot]":
            return True
    return False

def summarize_issue(issue, issue_category):
    """Summarize an issue for its section"""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    
    # Pre-format the Slack link with the correct repo name
    slack_link = f"<{issue['url']}|{issue['repo']}#{issue['number']}>"
    
    content = json.dumps({
        "issue": issue,
        "issue_category": issue_category
    }, ensure_ascii=False)
    
    prompt = f"""
    You are a support-engineering assistant summarizing a GitHub issues for a Slack digest.

    Input payload (JSON, provided as the user message):
      • `issue`  - metadata & full body text
      • `comments` - ALL comments with `is_recent_activity` flag indicating what's new
      • `issue_category` - one of "newly_opened", "updated", or "closed"

    Context usage:
    - Use ALL comments to understand the full conversation flow and issue history
    - Focus your summary on what changed in the recent time window (comments with `is_recent_activity: true`)
    - Reference relevant context from older comments when explaining recent activity
    - For "updated" issues, explain what the recent activity means in context of the overall issue progression

    General output rules
    --------------------
    • Produce ONE Slack-formatted bullet:
          • {slack_link} · *title* — <summary>
    • Use concise, active-voice fragments; ignore bot noise.
    • Be as detailed as needed—no token limit worries.
    • Quote logs/errors in ``` blocks when helpful.
    • DO NOT change the repo name or issue number - use exactly what's provided in the link above.

    Link formatting requirements
    --------------------------
    • ALWAYS convert any URL to a Slack hyperlink format: <url|descriptive text>
    • Never paste raw URLs in the summary text
    • Link to follow-up issues: If a bug report, feature request, or any follow-up issue was created, mention and link it using Slack format: <https://github.com/org/repo/issues/123|repo#123>
    • Link mentioned issues: When any issue is mentioned in the summary (e.g., "issue #45", "#123", "related to issue 67"), convert it to a proper Slack link: <https://github.com/org/repo/issues/45|repo#45>
    • Use the same repo name as the current issue unless explicitly stated otherwise
    • For cross-repo references, use the full repo name in the link text
    • If the exact repo isn't specified, assume same repo as current issue

    Checklist for **ALL** issues
    ----------------------------
    - **One-sentence problem statement** (from issue body or early comments)
    - Minimal repro steps (if present)
    - Key log line / error snippet (``` … ```)
    - Any workaround tried or suggested
    - Suspected root cause or product gap
    - Customer replies or expectations set
    - Notes from any support calls that occurred
    - **Follow-up issues created** (bug reports, feature requests, etc.) - MUST be linked
    - **Related issues mentioned** - MUST be linked

    Additional items by **issue_category**
    ------------------------------------
    ★ newly_opened
      - Customer / tenant & severity (Sev-1/2/3)
      - Environment (product & version, OS/K8s, etc.)
      - Any follow-up issues already created

    ★ updated
      - What changed in this window (new comments, labels, PR links)
      - How this fits into the overall issue progression
      - Decisions made or config changes applied
      - Progress state (e.g. needs a support bundle, waiting on customer reply, etc.)
      - New blockers or unanswered questions—flag clearly
      - Severity / priority changes
      - Follow-up issues created during this update

    ★ closed
      - Resolution type (fix, docs change, won't-fix, duplicate, etc.)
      - Confirmed root cause (one sentence)
      - Details on any workarounds tried or suggested
      - Who verified and how (customer confirmed, CI, etc.)
      - PR / commit link that closed it
      - Follow-up issues created - MUST be linked
      - Docs / KB updates
      - Total time-to-resolution (hours / days open)

    Examples (Slack Markdown)
    -------------------------
    # Example with follow-up issue (when one is actually mentioned/created):
    • <https://github.com/replicated-collab/progress-replicated/issues/123|progress-replicated#123> · *Cannot install on RHEL 9.3* — Issue where Embedded Cluster fails to install because Local Artifact Mirror fails to start. RHEL 9.3, Embedded Cluster v1.8.0. Logs indicate that Local Artifact Mirror failed to start because of SELinux. Customer put SELinux in permissive mode and the install succeeded. Feature request to support SELinux in enforcing mode: <https://github.com/replicated-collab/progress-replicated/issues/45|progress-replicated#45>.

    # Example without follow-up issue (when none are mentioned/created):
    • <https://github.com/replicated-collab/itrs-replicated/issues/456|itrs-replicated#456> · *KOTS fails to start on Ubuntu 22.04* — Customer reports KOTS application fails to start with "connection refused" error. Ubuntu 22.04, KOTS v1.95.0. Logs show port 8800 already in use. Customer confirmed no other KOTS instances running. Suggested checking for conflicting services on port 8800.

    (For **updated** and **closed** issues, swap in the relevant checklist items above.)
"""
    
    try:
        resp = client.chat.completions.create(
            model=get_openai_model(),
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": content},
            ],
            timeout=30,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERROR] Failed to summarize {issue['repo']}#{issue['number']}: {e}")
        return f"• {slack_link} · *{issue['title']}* — [Summarization failed]"

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
    
    # Convert UTC time to configured timezone for display
    since_local = since.astimezone(get_timezone())
    tz_abbrev = since_local.strftime("%Z")
    
    # Determine product name for the header
    if product_label:
        product_info = get_product_config(product_label)
        if product_info:
            product_name = product_info["product_config"]["name"]
        else:
            product_name = "Unknown"
    else:
        product_name = "Support"
    
    header = (
        f"*{product_name} Support Digest* "
        f"({time_desc} – since {since_local:%Y-%m-%d %H:%M} {tz_abbrev})"
    )
    return header

def get_product_label_by_shortname(shortname):
    """Return the product label (e.g., product::kots) for a given shortname, or None if not found."""
    config = get_config()
    for org_config in config["organizations"].values():
        for product_label, product_config in org_config["products"].items():
            if product_config.get("shortname") == shortname:
                return product_label
    return None

def run_for_product(product_label_or_shortname):
    """Run the support digest for a single product, accepting either a product label or a shortname."""
    # Try to resolve as shortname first
    resolved_label = get_product_label_by_shortname(product_label_or_shortname)
    if resolved_label:
        product_label = resolved_label
    else:
        product_label = product_label_or_shortname
    # Validate
    if product_label not in get_all_products():
        print(f"[ERROR] Product '{product_label_or_shortname}' not found in configuration (as label or shortname)")
        print(f"Available shortnames: {[p['shortname'] for org in get_config()['organizations'].values() for p in org['products'].values()]}")
        sys.exit(1)
    print(f"[DEBUG] Starting support digest script for {product_label}")
    
    # Get product configuration
    product_info = get_product_config(product_label)
    if not product_info:
        print(f"[ERROR] Product {product_label} not found in configuration")
        return
    
    product_config = product_info["product_config"]
    
    # Get configurable time window (default from config, fallback to env, then to config default)
    hours_back = int(os.environ.get("HOURS_BACK", str(get_default_hours_back())))
    print(f"[DEBUG] Looking back {hours_back} hours")
    
    gh    = Github(os.environ["GH_TOKEN"])
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_back)
    deltas = gather_deltas(gh, since, product_label)

    if deltas:
        text = summarize(deltas, since, hours_back, product_label)
        
        # Check if summarize returned None (no issues to report)
        if text is None:
            print(f"[DEBUG] No issues to report for {product_label} after filtering - skipping Slack message")
            return
        
        print(f"[DEBUG] Sending to Slack: {text[:1000]}...")
        
        # Check for dry run mode
        if os.environ.get("DRY_RUN"):
            print("DRY RUN MODE - Not sending to Slack")
            print(f"Summary:\n{text}")
        else:
            # Use product-specific webhook environment variable, otherwise fall back to default
            product_webhook_env = f"SLACK_WEBHOOK_{product_config.get('shortname', '').upper()}"
            webhook_url = os.environ.get(product_webhook_env) or os.environ.get("SLACK_WEBHOOK_URL")
            if not webhook_url:
                print(f"[ERROR] No webhook URL found for product {product_label}. Set {product_webhook_env} or SLACK_WEBHOOK_URL")
                return
            
            resp = WebhookClient(webhook_url).send(text=text)
            print(f"[DEBUG] Slack response: {resp.status_code} {resp.body}")
    else:
        print(f"[DEBUG] No deltas to report for {product_label}.")

def load_team_env():
    """Load environment variables from team-specific .env file"""
    try:
        config_file = os.environ.get("CONFIG_FILE", "config.installers.json")
        # Extract team name from config file (e.g., "config.installers.json" -> "installers")
        team_name = config_file.replace("config.", "").replace(".json", "")
        
        env_file = f".env.{team_name}"
        if os.path.exists(env_file):
            load_dotenv(env_file)
            print(f"[DEBUG] Loaded environment from {env_file}")
            return True
        else:
            print(f"[DEBUG] Team environment file {env_file} not found")
            return False
        
    except ImportError:
        print("[DEBUG] python-dotenv not installed - environment variables may not be loaded")
        return False

def main():
    print("[DEBUG] Starting support digest script")
    
    # Load team-specific environment
    load_team_env()
    
    # Load .env file only if no team-specific environment is set
    config_file = os.environ.get("CONFIG_FILE", "config.installers.json")
    # Accept shortname or product label as a command-line argument
    product_arg = sys.argv[1] if len(sys.argv) > 1 else None
    # Check if a specific product is requested
    product_label = product_arg or os.environ.get("PRODUCT_SHORTNAME")
    if product_label:
        # Run for a single product (label or shortname)
        run_for_product(product_label)
    else:
        # Run for all products separately
        all_products = get_all_products()
        print(f"[DEBUG] Running support digest for {len(all_products)} products separately")
        for label in all_products:
            print(f"\n[DEBUG] ===== Processing {label} =====")
            run_for_product(label)
            print(f"[DEBUG] ===== Completed {label} =====\n")

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

def summarize(deltas, since, hours_back, product_label=None):
    """New summarize function using categorization and parallel processing"""
    print(f"[DEBUG] Summarizing deltas ({len(deltas)} issues)")
    
    # Categorize issues using simple Python logic
    newly_opened, updated, closed = categorize_issues(deltas, since)
    
    # Check if any issues will be summarized
    total_issues = len(newly_opened) + len(updated) + len(closed)
    if total_issues == 0:
        return None  # Signal no content
    
    # Build digest with parallel processing
    summary = build_digest(newly_opened, updated, closed)
    
    # Format header
    header = format_header(since, hours_back, product_label)
    
    return f"{header}\n\n{summary}"

def categorize_issues(deltas, since):
    """
    Categorize pre-filtered issues:
    1. Closed - Issue is currently closed
    2. Newly Opened - Created in time window (and not closed)
    3. Updated - Has meaningful activity in time window (and not closed, not newly opened)
    """
    closed = []
    newly_opened = []
    updated = []
    
    for delta in deltas:
        # Issues are already pre-filtered, so we just categorize them
        if delta.get("state") == "closed":
            closed.append(delta)
            print(f"[DEBUG] {delta['repo']}#{delta['number']} → CLOSED")
        elif delta.get("created_at") >= since.isoformat():
            newly_opened.append(delta)
            print(f"[DEBUG] {delta['repo']}#{delta['number']} → NEWLY OPENED")
        else:
            updated.append(delta)
            print(f"[DEBUG] {delta['repo']}#{delta['number']} → UPDATED")
    
    print(f"[DEBUG] Categorization: {len(newly_opened)} new, {len(updated)} updated, {len(closed)} closed")
    return newly_opened, updated, closed

def process_issues_parallel(issues, issue_category, max_workers=None):
    """Process multiple issues in parallel"""
    if not issues:
        return []
    
    if max_workers is None:
        max_workers = get_max_workers()
    
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

if __name__ == "__main__":
    main() 