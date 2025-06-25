import os, json, datetime, textwrap
from zoneinfo import ZoneInfo
from github import Github
from slack_sdk.webhook import WebhookClient
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file for local development
load_dotenv()

ORG   = "replicated-collab"
LABELS = ["product::embedded-cluster", "product::kots", "product::kurl"]

# East Coast timezone
EAST_COAST_TZ = ZoneInfo("America/New_York")


def gather_deltas(gh, since):
    print(f"[DEBUG] Gathering deltas since {since.isoformat()}")
    all_deltas = []
    
    for label in LABELS:
        print(f"[DEBUG] Checking issues with label: {label}")
        query = f'is:issue label:"{label}" org:{ORG} updated:>{since.isoformat()}'
        issues = gh.search_issues(query, sort="updated", order="asc")
        deltas = []

        issue_count = 0
        for issue in issues:
            issue_count += 1
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
                "product_label": label,  # Add the product label for context
            }

            # ------- dynamic events -------
            events = []
            
            # Check for new comments in the time window
            for c in issue.get_comments(since):
                events.append({
                    "type": "comment",
                    "author": c.user.login,
                    "body": c.body,
                    "created_at": c.created_at.isoformat(),
                })

            # Check for state changes in the time window
            # We need to get the issue timeline to see state changes
            try:
                for event in issue.get_timeline():
                    if hasattr(event, 'event') and event.event == 'closed' and event.created_at >= since:
                        events.append({
                            "type": "state_change",
                            "state": "closed",
                            "created_at": event.created_at.isoformat(),
                        })
                    elif hasattr(event, 'event') and event.event == 'reopened' and event.created_at >= since:
                        events.append({
                            "type": "state_change",
                            "state": "reopened",
                            "created_at": event.created_at.isoformat(),
                        })
            except Exception as e:
                print(f"[DEBUG] Error getting timeline for issue {issue.number}: {e}")

            # Filter out issues where the only updates were by github-actions bot
            if events:
                # Check if all events are from github-actions bot
                # Only comment events have an author field, state changes don't
                comment_events = [event for event in events if event.get("type") == "comment"]
                state_change_events = [event for event in events if event.get("type") == "state_change"]
                
                # If there are state change events, we should include the issue (state changes are meaningful)
                if state_change_events:
                    deltas.append({**meta, "events": events})
                # If there are only comment events, check if they're all from github-actions bot
                elif comment_events:
                    all_github_actions_comments = all(
                        event.get("author") == "github-actions[bot]" 
                        for event in comment_events
                    )
                    
                    # If all comments are from github-actions bot, skip this issue
                    if all_github_actions_comments:
                        print(f"[DEBUG] Skipping issue {issue.number} - only github-actions bot comments")
                        continue
                    
                    deltas.append({**meta, "events": events})
                else:
                    # Fallback case - include the issue
                    deltas.append({**meta, "events": events})

        print(f"[DEBUG] Retrieved {issue_count} issues for {label}, {len(deltas)} with deltas.")
        all_deltas.extend(deltas)
    
    print(f"[DEBUG] Total deltas across all labels: {len(all_deltas)}")
    return all_deltas


def summarize(deltas, since, hours_back):
    print(f"[DEBUG] Summarizing deltas ({len(deltas)} issues)")
    client  = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    
    # Add the since timestamp to the data for the AI to use
    data_with_since = {
        "since_timestamp": since.isoformat(),
        "deltas": deltas
    }
    content = json.dumps(data_with_since, ensure_ascii=False)
    
    prompt  = textwrap.dedent(f"""
        You are *Support Digest Bot* for Replicated's **installers** (Embedded Cluster and KOTS).

        INPUT
        • A JSON object containing:
          - since_timestamp: the start of the delta window (ISO timestamp)
          - deltas: array of issue objects, each containing:
            - title        : issue title (string)
            - number       : issue number (int)
            - repo         : repository name (string)
            - url          : HTML link (string)
            - labels       : array of label strings
            - body         : original issue body (string, may be long)
            - created_at   : when the issue was created (ISO timestamp)
            - updated_at   : when the issue was last updated (ISO timestamp)
            - state        : current state ("open" or "closed")
            - product_label: the product label ("product::embedded-cluster" or "product::kots")
            - events       : array of delta events (only since last digest)
                  • For "comment" events:  author, body, created_at
                  • For "state_change" events:  state ("closed" or "reopened"), created_at

        TASK
        Produce a **Slack-ready markdown** digest with three sections:

        *Newly Opened Issues*  
         • For every issue that was **created** in this delta window (created_at >= since_timestamp) list a bullet:  
           `• <url|repo#number> · *title*` — followed by a **thorough** synopsis (no hard length cap).  
           Include: problem description, environment, commands tried, workarounds, blockers, and any **feature gap / bug** you detect.  
           If the conversation shows that a **new bug or feature-request issue was opened** (look for a GitHub link plus words like
           "opened", "created", "filed"), mention it inline:  
           `   ↳ Bug opened: <linked-url|#id> · **title**` or  
           `   ↳ Feature request: <linked-url|#id> · **title**`.
           Prefix possible gaps with `⚠️ Potential product gap:`.  
           Quote exact commands or code blocks using triple back-ticks when helpful.
           **Indicate the product** (Embedded Cluster or KOTS) at the beginning of each bullet.

        *Updated Issues*  
         • Bullet for each issue that was **created before** this delta window but has **comment events** or **state changes** in the delta.  
           Begin the same way (`• <url|repo#number> · *title*`).  
           Summarize **only the new comments and state changes**, weaving in title/labels/body for context.  
           If any comment indicates a fresh bug or feature issue was filed, append an indented line with the same
           `↳ Bug opened:` / `↳ Feature request:` pattern and link.
           Explain new insights, progress, workarounds, next steps.  
           **IMPORTANT**: If an issue has any comment events or state_change events, it MUST be included in this section.
           Skip issues whose only changes were label edits (no comments or state changes).
           **Indicate the product** (Embedded Cluster or KOTS) at the beginning of each bullet.

        *Closed Issues*  
         • Bullet for each issue that transitioned to *closed* in the delta (has a "state_change" event with state "closed").  
           Format: `• <url|repo#number> · *title* — Closed · <reason or closing comment>`.
           **Indicate the product** (Embedded Cluster or KOTS) at the beginning of each bullet.

        STYLE & RULES
        1. Use Slack markdown: `*bold*`, `_italic_`, ```code```, and triple-back-tick blocks.  
        2. Links **must** use Slack inline format: `<url|repo#number>`.  
        3. Be as detailed as needed; no summary length limit.  
        4. GitHub handles are fine to include as plain text (e.g., `octocat`), **but do not use Slack @-mentions or `<@U123>` syntax**.  
        5. When linking bug/feature issues, always use Slack inline link format `<url|#number>`; keep the "↳" prefix so these call-outs stand out.
        6. If an issue body is too long for context, include only the portions essential to understand the problem.  
        7. Preserve Unicode bullets and clear indentation for readability.  
        8. Return **only** the digest text—no extra headings, metadata, or commentary.
        9. **CRITICAL**: Use the created_at timestamp to determine if an issue is "newly opened" vs "updated". Only issues created within the delta window should go in "Newly Opened Issues".
        10. **CRITICAL**: Every issue with comment events or state_change events MUST be included in the appropriate section. Do not skip any issues that have events.
        11. **CRITICAL**: Start each bullet with the product indicator: `[Embedded Cluster]` or `[KOTS]` followed by the rest of the bullet.
        12. If a category (new, updated, closed) is empty, do not include it in the output.

        OUTPUT EXAMPLE (follow this structure exactly)

        *Replicated Installers Support Digest* (past 24h - since 2025-06-24 12:00 ET)

        *Newly Opened Issues*  
        • [Embedded Cluster] <https://github.com/org/repo/issues/123|progress-replicated#123> · *Install fails on SELinux* — The installer errors on …  
         Workaround tried:  
         ```bash
         setenforce 0
         ```  
         ⚠️ Potential product gap: SELinux-aware install path …

        • [KOTS] <https://github.com/org/repo/issues/124|kots-repo#124> · *Application deployment fails* — The KOTS application fails to deploy with …

        *Updated Issues*  
        • [Embedded Cluster] <https://github.com/org/repo/issues/99|acme-corp#99> · *Preflight check timeout* — New comment indicates …  

        *Closed Issues*  
        • [KOTS] <https://github.com/org/repo/issues/87|tech-startup#87> · *CI pipeline hangs* — Closed · Fixed in v1.2.3
    """)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ],
    )
    summary = resp.choices[0].message.content.strip()
    print(f"[DEBUG] OpenAI summary: {summary[:1000]}...")
    
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
    
    header = (
        f"*Replicated Installers Support Digest* "
        f"({time_desc} – since {since_east_coast:%Y-%m-%d %H:%M ET})"
    )
    return f"{header}\n\n{summary}"


def main():
    print("[DEBUG] Starting support digest script")
    
    # Get configurable time window (default 24 hours)
    hours_back = int(os.environ.get("HOURS_BACK", "24"))
    print(f"[DEBUG] Looking back {hours_back} hours")
    
    gh    = Github(os.environ["GH_TOKEN"])
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_back)
    deltas = gather_deltas(gh, since)

    if deltas:
        text = summarize(deltas, since, hours_back)
        print(f"[DEBUG] Sending to Slack: {text[:1000]}...")
        
        # Check for dry run mode
        if os.environ.get("DRY_RUN"):
            print("DRY RUN MODE - Not sending to Slack")
            print(f"Summary:\n{text}")
        else:
            resp = WebhookClient(os.environ["SLACK_WEBHOOK_URL"]).send(text=text)
            print(f"[DEBUG] Slack response: {resp.status_code} {resp.body}")
    else:
        print("[DEBUG] No deltas to report.")


if __name__ == "__main__":
    main()
