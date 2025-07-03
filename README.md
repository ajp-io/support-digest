# Support Digest

This repository contains scripts to generate support digests for GitHub issues by analyzing issues and comments across multiple products and organizations.

## Overview

The support digest script monitors GitHub issues across configured organizations and generates summaries of:
- Newly opened issues
- Updated issues with new comments or state changes
- Closed issues

## Quick Start

For detailed setup instructions, see [SETUP.md](SETUP.md).

## Configuration

The script is fully configurable through a JSON configuration file (`config.json`). This allows different teams to easily set up their own products without modifying the code.

### Configuration Structure

```json
{
  "organizations": {
    "your-org-name": {
      "name": "Your Organization Name",
      "products": {
        "product::your-product": {
          "name": "Your Product",
          "shortname": "yourproduct",
          "github_org": "your-org-name",
          "issue_labels": ["kind::inbound-escalation", "support"]
        }
      }
    }
  },
  "defaults": {
    "hours_back": 24,
    "timezone": "America/New_York",
    "max_workers": 10,
    "openai_model": "gpt-4o-mini"
  }
}
```

### Configuration Fields

#### Organization
- `name`: Display name for the organization

#### Product
- `name`: Name for the product (used for display)
- `shortname`: Short identifier for command-line usage (e.g., "kots", "ec")
- `github_org`: GitHub organization name
- `issue_labels`: Array of general labels that issues must have to be included (e.g., "kind::inbound-escalation"). The product-specific label (e.g., "product::kots") is automatically included based on the configuration key.

#### Defaults
- `hours_back`: Default time window to look back (can be overridden by `HOURS_BACK` env var)
- `timezone`: Timezone for displaying timestamps
- `max_workers`: Maximum parallel workers for processing issues
- `openai_model`: OpenAI model to use for summarization
- `github_action_schedule`: Cron schedule for GitHub Actions (optional, defaults to daily at 7:00 PM UTC)

## Products Supported

The script supports any products configured in `config.json`. By default, it includes:

- **KOTS** (shortname: `kots`)
- **kURL** (shortname: `kurl`) 
- **Embedded Cluster** (shortname: `ec`)

## Usage

### Local Development

#### Run for All Products

This runs the digest for all configured products separately:

```bash
./run_local.sh
```

#### Run for a Specific Product

Use the product's shortname:

```bash
./run_product.sh kots
./run_product.sh kurl
./run_product.sh ec
```

Or run directly:

```bash
python3 support_digest.py kots
```

#### Environment Variables for Local Development

Create a `.env` file based on `env.example`:

```bash
cp env.example .env
```

Required environment variables:
- `GH_TOKEN`: GitHub Personal Access Token with org access
- `OPENAI_API_KEY`: OpenAI API key for generating summaries
- `SLACK_WEBHOOK_URL`: Slack webhook URL for posting results

Optional environment variables:
- `HOURS_BACK`: Time window to look back (overrides config default)
- `DRY_RUN`: Set to any value to skip Slack posting (for testing)

### GitHub Actions (Production)

The digest runs automatically via GitHub Actions:
- **Schedule**: Daily at 7:00 PM UTC (configurable via `github_action_schedule`)
- **Manual**: Can be triggered manually via workflow dispatch with optional product selection

#### GitHub Secrets Required

In your repository's Settings → Secrets and variables → Actions, add:
- `GH_TOKEN`: GitHub Personal Access Token
- `OPENAI_API_KEY`: OpenAI API key
- `SLACK_WEBHOOK_URL`: Slack webhook URL

#### Manual Workflow Dispatch

When manually triggering the workflow, you can optionally specify a product shortname to run for just that product.

## Architecture

The script processes GitHub issues through a consolidated discovery and filtering approach:

### 1. Issue Discovery & Filtering
- **GitHub API Queries**: Uses two precise searches to minimize false positives:
  - `created:>timestamp` for newly opened issues
  - `updated:>timestamp` for recently updated issues
- **Label Filtering**: Only includes issues with all required product and support labels
- **Bot Activity Filtering**: Excludes issues that only have bot comments (e.g., `github-actions[bot]`)
- **Efficient Data Fetching**: Only fetches comments for issues that pass initial filtering

### 2. Issue Categorization
Issues are categorized into three types:
- **Newly Opened**: Created within the time window
- **Updated**: Has new non-bot comments within the time window  
- **Closed**: Currently closed (regardless of when closed)

### 3. Parallel Processing
- Each product is processed independently to avoid context window limitations
- Issues within each product are processed in parallel (configurable via `max_workers`)
- Each issue's comments are analyzed for recent meaningful activity

### 4. AI Summarization
- Each issue is summarized using OpenAI's API
- The prompt includes the full issue context and recent activity, with AI summaries focusing on recent comments but using the whole issue history for context
- Summaries are formatted for Slack with GitHub links and issue numbers

### 5. Error Handling
- Individual issue failures don't stop processing of other issues
- Fallback to basic issue information if AI summarization fails
- Timeout handling for OpenAI API calls (30 seconds)
- Graceful degradation when individual API calls fail

## Output Format

The digest is formatted for Slack with sections for:
- **Newly Opened Issues**: Issues created within the time window
- **Updated Issues**: Existing issues with new activity
- **Closed Issues**: Issues that were closed within the time window

Each issue includes:
- Product indicator (from configuration)
- GitHub link and issue number
- Issue title
- Summary of activity and context