import os, json, datetime, textwrap
from github import Github
from slack_sdk.webhook import WebhookClient
from openai import OpenAI

ORG   = "replicated-collab"
LABEL = "product::embedded-cluster"


def gather_deltas(gh, since):
    print(f"[DEBUG] Gathering deltas since {since.isoformat()}")
    query = f'is:issue label:"{LABEL}" org:{ORG} updated:>{since.isoformat()}'
    issues = gh.search_issues(query, sort="updated", order="asc")
    deltas = []

    issue_count = 0
    for issue in issues:
        issue_count += 1
        # ------- always‑included static context -------
        meta = {
            "title": issue.title,
            "number": issue.number,
            "labels": [l.name for l in issue.labels],
            "body": (issue.body or ""),
            "url": issue.html_url,
        }

        # ------- 24‑hour dynamic events -------
        events = []
        for c in issue.get_comments(since):
            events.append({
                "type": "comment",
                "author": c.user.login,
                "body": c.body,
                "created_at": c.created_at.isoformat(),
            })

        if issue.updated_at >= since and issue.state in ("closed", "open"):
            events.append({
                "type": "state",
                "state": issue.state,
                "updated_at": issue.updated_at.isoformat(),
            })

        if events:
            deltas.append({**meta, "events": events})

    print(f"[DEBUG] Retrieved {issue_count} issues, {len(deltas)} with deltas.")
    print(f"[DEBUG] Deltas: {json.dumps(deltas, indent=2, ensure_ascii=False)[:1000]}...")
    return deltas


def summarize(deltas, since):
    print(f"[DEBUG] Summarizing deltas ({len(deltas)} issues)")
    client  = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    content = json.dumps(deltas, ensure_ascii=False)
    prompt  = textwrap.dedent(f"""
        You are Support Digest Bot for Replicated's Embedded Cluster product.
        Summarize the JSON of issue deltas provided. Produce:
        1. Newly opened issues (title · #id · link).
        2. Issues closed or re‑opened.
        3. For still‑open issues, highlight any comment containing
           "workaround", "blocked", or a code block.
        4. Note any @alexp mention.
        Each issue object includes static context (title, labels, body) to help
        you interpret terse comments—use it wisely. Limit output to **250 words**.
        Return Slack‑friendly markdown only.
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
    header = (
        f"*Embedded‑Cluster Support Digest* "
        f"(past 24 h – since {since:%Y-%m-%d %H:%M UTC})"
    )
    return f"{header}\n{summary}"


def main():
    print("[DEBUG] Starting support digest script")
    gh    = Github(os.environ["GH_TOKEN"])
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    deltas = gather_deltas(gh, since)

    if deltas:
        text = summarize(deltas, since)
        print(f"[DEBUG] Sending to Slack: {text[:1000]}...")
        resp = WebhookClient(os.environ["SLACK_WEBHOOK_URL"]).send(text=text)
        print(f"[DEBUG] Slack response: {resp.status_code} {resp.body}")
    else:
        print("[DEBUG] No deltas to report.")


if __name__ == "__main__":
    main()
