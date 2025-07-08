# Quick Setup Guide for Teams

This guide will help you set up the support digest script for your team's products.

## Step 1: Clone and Configure

1. Clone this repository:
   ```bash
   git clone <your-repository-url>
   cd support-digest
   ```

   **Note:** Replace `<your-repository-url>` with the URL of your fork of this repository.

2. Copy the example configuration:
   ```bash
   cp config.example.json config.json
   ```

3. Edit `config.json` to add your organization and products:
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
       "openai_model": "gpt-4o-mini",
       "max_tokens": 1000
     }
   }
   ```

## Step 2: Validate Configuration

Run the validation script to check your configuration:

```bash
python3 validate_config.py
```

This will verify:
- All required fields are present and valid
- Your GitHub token is valid and has the necessary permissions
- You have access to the configured organizations
- Sample repositories exist and are accessible
- The specified issue labels exist in your repositories (sampled from each organization)
- Your OpenAI API key is valid (if provided)

The validation script provides detailed feedback about any issues found and suggestions for fixing them.

## Step 3: Set Up Environment Variables

1. Copy the example environment file:
   ```bash
   cp env.example .env
   ```

2. Edit `.env` with your credentials:
   ```bash
   # GitHub Personal Access Token (needs repo access for your configured organizations)
   GH_TOKEN=your_github_pat_here

   # OpenAI API Key
   OPENAI_API_KEY=your_openai_api_key_here

   # Slack Webhook URL
   SLACK_WEBHOOK_URL=your_slack_webhook_url_here
   ```

## Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

## Step 5: Test Your Setup

1. Test with dry run mode:
   ```bash
   DRY_RUN=1 ./run_local.sh
   ```

2. Test a specific product:
   ```bash
   ./run_product.sh kots
   ./run_product.sh ec
   ./run_product.sh kurl
   ./run_product.sh troubleshoot
   ```
   Or directly:
   ```bash
   python3 support_digest.py kots
   ```

## Step 6: Run for Real

Once you're satisfied with the test output:

```bash
# Run for all products
./run_local.sh

# Run for a specific product
./run_product.sh yourproduct
```

Replace `yourproduct` with the shortname you defined in your configuration.

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

## Troubleshooting

### Configuration Issues

- Run `python3 validate_config.py` to check for configuration errors
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
3. Validate your configuration with `python3 validate_config.py`
4. Check the main README.md for more detailed documentation 