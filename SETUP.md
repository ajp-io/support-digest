# Support Digest Setup Guide

This guide will help you set up the support digest script for your team's products.

## Overview

The support digest system uses a team-based approach where each team has:
- **Separate configuration file** (e.g., `config.installers.json`)
- **Separate GitHub Actions workflow** (e.g., `support-digest-installers.yaml`)
- **Separate Slack webhook** (stored as GitHub secret)

### Benefits

✅ **Complete isolation** - Teams don't interfere with each other
✅ **Flexibility** - Each team can customize their setup independently  
✅ **Security** - Each team manages their own secrets
✅ **Reliability** - If one team's config breaks, others keep running
✅ **Maintainability** - Easy to add new teams without code changes

## Team Configurations

### Installers Team
- **Config**: `config.installers.json`
- **Workflow**: `support-digest-installers.yaml`
- **Webhook Secret**: `SLACK_WEBHOOK_INSTALLERS`
- **Products**: KOTS, kURL, Embedded Cluster, Troubleshoot

### Vendor Experience Team  
- **Config**: `config.vendex.json`
- **Workflow**: `support-digest-vendex.yaml`
- **Webhook Secret**: `SLACK_WEBHOOK_VENDEX`
- **Products**: Vendor Portal, Replicated SDK, Helm CLI, Download Portal

### Compatibility Matrix Team
- **Config**: `config.cmx.json`
- **Workflow**: `support-digest-cmx.yaml`
- **Webhook Secret**: `SLACK_WEBHOOK_CMX`
- **Products**: Compatibility Matrix

## Local Development Setup

### Step 1: Clone and Configure

1. Clone this repository:
   ```bash
   git clone <your-repository-url>
   cd support-digest
   ```

   **Note:** Replace `<your-repository-url>` with the URL of your fork of this repository.

2. Validate your team's configuration:
   ```bash
   # Validate installers team configuration
   python3 validate_config.py installers
   
   # Validate vendex team configuration
   python3 validate_config.py vendex
   
   # Validate compatibility-matrix team configuration
   python3 validate_config.py cmx
   
   # List all available teams
   python3 validate_config.py --list
   ```

3. Edit your team's config file to add your organization and products:
   ```json
   {
     "organizations": {
       "your-company": {
         "name": "Your Company",
         "products": {
           "product::your-product": {
             "name": "Your Product",
             "shortname": "yourproduct",
             "github_org": "your-company",
             "issue_labels": ["kind::inbound-escalation"]
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

### Step 2: Validate Configuration

Run the validation script to check your team's configuration:

```bash
# Validate a specific team
python3 validate_config.py installers
python3 validate_config.py vendex
python3 validate_config.py cmx

# List available teams
python3 validate_config.py --list
```

This will verify:
- All required fields are present and valid
- Your GitHub token is valid and has the necessary permissions
- You have access to the configured organizations
- Sample repositories exist and are accessible
- The specified issue labels exist in your repositories (sampled from each organization)
- Your OpenAI API key is valid (if provided)

The validation script provides detailed feedback about any issues found and suggestions for fixing them.

### Step 3: Set Up Environment Variables

1. Copy the example environment file for your team:
   ```bash
   # For Installers team
   cp env.example .env.installers
   
   # For Vendor Experience team
   cp env.example .env.vendex
   
   # For Compatibility Matrix team
   cp env.example .env.cmx
   ```

2. Edit your team's `.env.<team>` file with your credentials:
   ```bash
   # GitHub Personal Access Token (needs repo access for your configured organizations)
   GH_TOKEN=your_github_pat_here

   # OpenAI API Key
   OPENAI_API_KEY=your_openai_api_key_here

   # Slack Webhook URL
   SLACK_WEBHOOK_URL=your_slack_webhook_url_here
   ```

### Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 5: Test Your Setup

1. Test with dry run mode:
   ```bash
   # Test Installers team (default)
   DRY_RUN=1 ./run_local.sh
   
   # Test specific team
   DRY_RUN=1 ./run_local.sh vendex
   DRY_RUN=1 ./run_local.sh cmx
   ```

2. Test a specific product:
   ```bash
   # Installers team products
   ./run_product.sh kots
   ./run_product.sh ec
   ./run_product.sh kurl
   ./run_product.sh troubleshoot
   
   # Vendor Experience team products
   ./run_product.sh vendex vp
   ./run_product.sh vendex sdk
   
   # Compatibility Matrix team products
   ./run_product.sh cmx cmx
   ```
   Or directly:
   ```bash
   python3 support_digest.py kots
   ```

### Step 6: Run for Real

Once you're satisfied with the test output:

```bash
# Run for all products (defaults to installers team)
./run_local.sh

# Run for specific team
./run_local.sh vendex
./run_local.sh cmx

# Run for a specific product
./run_product.sh kots        # Installers team, KOTS product
./run_product.sh vendex vp   # Vendex team, Vendor Portal product
./run_product.sh cmx cmx     # Compatibility Matrix team, Compatibility Matrix product
```

Replace the team and product names with your specific configuration.

## GitHub Actions Setup (Production)

### GitHub Secrets Required

Add these secrets to your repository (Settings → Secrets and variables → Actions):

**Required for All Teams:**
- `GH_TOKEN`: GitHub Personal Access Token
- `OPENAI_API_KEY`: OpenAI API key

**Team-Specific Webhooks:**
- `SLACK_WEBHOOK_INSTALLERS`: Installers team webhook
- `SLACK_WEBHOOK_VENDEX`: Vendor Experience team webhook  
- `SLACK_WEBHOOK_CMX`: Compatibility Matrix team webhook

### Workflow Schedules

All workflows run daily at 7:00 PM UTC, but each can be:
- **Manually triggered** with optional product selection
- **Independently scheduled** (if teams want different times)
- **Independently disabled** (if a team needs to pause)

### Manual Workflow Dispatch

When manually triggering the workflow, you can optionally specify a product shortname to run for just that product.

## Configuration Options

### Issue Labels

The `issue_labels` array defines which GitHub issue labels must be present for an issue to be included in the digest. This consolidates all label configuration in one place.

**Recommended pattern:**
```json
"issue_labels": ["kind::inbound-escalation"]
```

This will only include issues that have ALL the specified labels:
- `kind::inbound-escalation`: General label for escalation issues

**Note:** The product-specific label (e.g., `product::kots`) is automatically included based on the configuration key, so you don't need to specify it in the `issue_labels` array.

You can customize this array based on your team's labeling conventions. For example, some teams use `support` or `escalation` instead of `kind::inbound-escalation`. The validation script will check that all specified labels exist in your repositories.

### Timezone

Set your preferred timezone for displaying timestamps:

```json
"timezone": "America/Los_Angeles"
```

### Time Window

Set the default time window to look back:

```json
"hours_back": 48
```

You can also override this with the `HOURS_BACK` environment variable.

### OpenAI Model

Choose which OpenAI model to use for summarization:

```json
"openai_model": "gpt-4o-mini"
```

## Adding New Teams

To add a new team:

1. **Create config file**: `config.new-team.json`
2. **Create workflow**: `support-digest-new-team.yaml`
3. **Add webhook secret**: `SLACK_WEBHOOK_NEW_TEAM`
4. **Update documentation**

## Testing

Test individual teams using the unified scripts:

```bash
# Test Installers team (default)
./run_local.sh                    # All installers products
./run_product.sh kots             # Just KOTS
./run_product.sh installers kots  # Explicit installers team

# Test Vendex team
./run_local.sh vendex       # All vendex products
./run_product.sh vendex vp  # Just Vendor Portal

# Test Compatibility Matrix team
./run_local.sh cmx        # All compatibility matrix products
./run_product.sh cmx cmx  # Just Compatibility Matrix
```

## Troubleshooting

### Configuration Issues

- Run `python3 validate_config.py <team>` to check for configuration errors
- Ensure all required fields are present in your product configuration
- Check that your GitHub organization name matches exactly

### Permission Issues

- Ensure your GitHub token has access to the repositories in your configured organizations
- Verify your Slack webhook URL is correct and active

### No Issues Found

- Check that your issue labels exist in your GitHub repositories
- Verify that issues have been updated within your time window
- Try increasing the `HOURS_BACK` value to look further back

## Support

If you encounter issues:

1. Check the debug output for error messages
2. Run with `DRY_RUN=1` to see what would be processed without sending to Slack
3. Validate your configuration with `python3 validate_config.py <team>`
4. Check the main README.md for more detailed documentation 