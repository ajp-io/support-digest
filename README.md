# Support Digest

This repository contains scripts to generate support digests for GitHub issues by analyzing issues and comments across multiple products and organizations.

## Overview

The support digest script monitors GitHub issues across configured organizations and generates summaries of:
- Newly opened issues
- Updated issues with new comments or state changes
- Closed issues

## Quick Start

For detailed setup instructions, see [SETUP.md](SETUP.md).

### Configuration Validation

Before running the digest, validate your team's configuration:

```bash
# Validate a specific team
python3 validate_config.py installers
python3 validate_config.py vendex
python3 validate_config.py compatibility-matrix

# List available teams
python3 validate_config.py --list
```

This validates your configuration, GitHub access, and environment setup.

## Configuration

The script is fully configurable through a team-specific JSON configuration file. This allows different teams to easily set up their own products without modifying the code.

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

## Teams and Products Supported

The repository supports multiple teams with separate workflows and configurations. Each team has their own:

- **Configuration file** (e.g., `config.installers.json`)
- **GitHub Actions workflow** (e.g., `support-digest-installers.yaml`)
- **Slack webhook** (stored as GitHub secret)

### Installers Team
- **Configuration**: `config.installers.json`
- **Workflow**: `support-digest-installers.yaml`
- **Webhook Secret**: `SLACK_WEBHOOK_INSTALLERS`
- **Products**:
  - **KOTS** (shortname: `kots`)
  - **kURL** (shortname: `kurl`) 
  - **Embedded Cluster** (shortname: `ec`)
  - **Troubleshoot** (shortname: `troubleshoot`)

### Vendor Experience Team
- **Configuration**: `config.vendex.json`
- **Workflow**: `support-digest-vendex.yaml`
- **Webhook Secret**: `SLACK_WEBHOOK_VENDEX`
- **Products**:
  - **Vendor Portal** (shortname: `vp`)
  - **Replicated SDK** (shortname: `sdk`)
  - **Helm CLI** (shortname: `helm`)
  - **Download Portal** (shortname: `dp`)

### Compatibility Matrix Team
- **Configuration**: `config.cmx.json`
- **Workflow**: `support-digest-cmx.yaml`
- **Webhook Secret**: `SLACK_WEBHOOK_CMX`
- **Products**:
  - **Compatibility Matrix** (shortname: `cmx`)

## Usage

### Local Development

#### Run for All Products

This runs the digest for all configured products separately:

```bash
# Run installers team (default)
./run_local.sh

# Run specific team
./run_local.sh installers
./run_local.sh vendex
./run_local.sh compatibility-matrix
```

#### Run for a Specific Product

Use the product's shortname:

```bash
# Run installers team, KOTS product (default team)
./run_product.sh kots

# Run specific team and product
./run_product.sh installers kots
./run_product.sh vendex vp
./run_product.sh compatibility-matrix cmx
```

Or run directly:

```bash
python3 support_digest.py kots
```

#### Environment Variables for Local Development

The system uses team-specific environment files for local development. To set up your environment:

1. Copy the example file to your team-specific env file:
```bash
cp env.example .env.installers            # For Installers team
cp env.example .env.vendex     # For Vendor Experience team
cp env.example .env.compatibility-matrix  # For Compatibility Matrix team
```

2. Edit your `.env.<team>` file to contain your real secrets and webhooks.

**Note**: Each team uses a separate environment file to support different Slack webhooks and configurations. The script automatically detects which team you're running and loads the appropriate `.env.<team>` file.

Required environment variables (for all teams):
- `GH_TOKEN`: GitHub Personal Access Token with org access
- `OPENAI_API_KEY`: OpenAI API key for generating summaries
- `SLACK_WEBHOOK_URL`: Team's Slack webhook URL

Optional environment variables:
- `HOURS_BACK`: Time window to look back (overrides config default)
- `DRY_RUN`: Set to any value to skip Slack posting (for testing)

### GitHub Actions (Production)

The digest runs automatically via GitHub Actions:
- **Manual**: Can be triggered manually via workflow dispatch with optional product selection

#### GitHub Secrets Required

Each team workflow requires these secrets in your repository's Settings → Secrets and variables → Actions:

**All Teams:**
- `GH_TOKEN`: GitHub Personal Access Token
- `OPENAI_API_KEY`: OpenAI API key

**Team-Specific Webhooks:**
- `SLACK_WEBHOOK_INSTALLERS`: Installers team webhook
- `SLACK_WEBHOOK_VENDEX`: Vendor Experience team webhook  
- `SLACK_WEBHOOK_CMX`: Compatibility Matrix team webhook

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

### 3. GitHub Issue Processing
- Each product is processed independently to avoid context window limitations
- GitHub issues within each product are processed in parallel (configurable via `max_workers`)
- Each issue's comments are analyzed for recent meaningful activity

### 4. AI Summarization
- Each issue is summarized using OpenAI's API in parallel (using the same `max_workers` configuration)
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