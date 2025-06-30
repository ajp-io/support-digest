#!/usr/bin/env python3
"""
Configuration validation script for support digest.
Run this to validate your config.json before running the main script.
"""

import json
import sys
import os
from zoneinfo import ZoneInfo

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not installed, continue without it
    pass

def validate_github_access(config):
    """Validate GitHub access if GH_TOKEN is available"""
    if not os.environ.get("GH_TOKEN"):
        print("  ⚠️  GH_TOKEN not set - skipping GitHub access validation")
        return True
    
    try:
        from github import Github
        gh = Github(os.environ["GH_TOKEN"])
        
        print("  🔍 Validating GitHub access...")
        
        # Test token validity
        try:
            user = gh.get_user()
            print(f"  ✅ GitHub token valid (authenticated as: {user.login})")
        except Exception as e:
            print(f"  ❌ GitHub token invalid: {e}")
            return False
        
        # Check organization access
        for org_name, org_config in config["organizations"].items():
            print(f"    📋 Checking access to organization: {org_name}")
            
            try:
                org = gh.get_organization(org_name)
                org_display_name = org.name or org.login  # Use login if name is None
                print(f"      ✅ Can access organization: {org_display_name}")
                
                # Check if we can list repositories
                all_repos = list(org.get_repos())
                repos = all_repos[:5]  # Just check first 5 repos
                if repos:
                    print(f"      ✅ Can access repositories (sampling first 5 of {len(all_repos)} total)")
                else:
                    print(f"      ⚠️  No repositories found in organization")
                
                # Check product configurations
                for product_label, product_config in org_config["products"].items():
                    print(f"        📦 Checking product: {product_config['name']}")
                    
                    # Check if labels exist in any repository
                    labels_found = False
                    for repo in repos[:3]:  # Check first 3 repos
                        try:
                            repo_labels = list(repo.get_labels())
                            label_names = [label.name for label in repo_labels]
                            
                            for required_label in product_config["issue_labels"]:
                                if required_label in label_names:
                                    labels_found = True
                                    print(f"          ✅ Label '{required_label}' found in {repo.name}")
                                    break
                            
                            if labels_found:
                                break
                        except Exception as e:
                            print(f"          ⚠️  Could not check labels in {repo.name}: {e}")
                    
                    if not labels_found:
                        print(f"          ⚠️  Warning: Required labels {product_config['issue_labels']} not found in first few repositories")
                        print(f"          💡 Make sure these labels exist in your repositories")
                
            except Exception as e:
                print(f"      ❌ Cannot access organization {org_name}: {e}")
                print(f"      💡 Check that your GitHub token has access to this organization")
                return False
        
        return True
        
    except ImportError:
        print("  ⚠️  PyGithub not installed - skipping GitHub access validation")
        print("  💡 Install with: pip install PyGithub")
        return True
    except Exception as e:
        print(f"  ❌ GitHub validation failed: {e}")
        return False

def validate_config(config_path="config.json"):
    """Validate the configuration file"""
    print(f"Validating configuration file: {config_path}")
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"❌ Configuration file {config_path} not found")
        print("Please copy config.example.json to config.json and configure it for your team")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in configuration file: {e}")
        return False
    
    print("✅ Configuration file loaded successfully")
    
    # Validate structure
    if "organizations" not in config:
        print("❌ Missing 'organizations' section in configuration")
        return False
    
    if "defaults" not in config:
        print("❌ Missing 'defaults' section in configuration")
        return False
    
    print("✅ Configuration structure is valid")
    
    # Validate organizations
    organizations = config["organizations"]
    if not organizations:
        print("❌ No organizations configured")
        return False
    
    total_products = 0
    for org_name, org_config in organizations.items():
        print(f"\n📋 Organization: {org_name}")
        
        if "name" not in org_config:
            print(f"  ❌ Missing 'name' for organization {org_name}")
            return False
        
        if "products" not in org_config:
            print(f"  ❌ Missing 'products' for organization {org_name}")
            return False
        
        products = org_config["products"]
        if not products:
            print(f"  ⚠️  No products configured for organization {org_name}")
            continue
        
        print(f"  ✅ {org_config['name']} - {len(products)} products")
        
        # Validate each product
        for product_label, product_config in products.items():
            print(f"    📦 Product: {product_label}")
            
            required_fields = ["name", "shortname", "github_org", "issue_labels"]
            for field in required_fields:
                if field not in product_config:
                    print(f"      ❌ Missing '{field}' for product {product_label}")
                    return False
            
            if not product_config["issue_labels"]:
                print(f"      ❌ No issue labels configured for product {product_label}")
                return False
            
            print(f"      ✅ {product_config['name']} ({product_config['github_org']})")
            print(f"         Shortname: {product_config.get('shortname', 'NOT SET')}")
            print(f"         Labels: {', '.join(product_config['issue_labels'])}")
            total_products += 1
    
    print(f"\n✅ Total products configured: {total_products}")
    
    # Validate defaults
    defaults = config["defaults"]
    print(f"\n📋 Defaults:")
    
    # Validate timezone
    if "timezone" in defaults:
        try:
            ZoneInfo(defaults["timezone"])
            print(f"  ✅ Timezone: {defaults['timezone']}")
        except Exception as e:
            print(f"  ❌ Invalid timezone '{defaults['timezone']}': {e}")
            return False
    else:
        print("  ⚠️  No timezone configured, will use America/New_York")
    
    # Validate other defaults
    default_fields = {
        "hours_back": (int, 24),
        "max_workers": (int, 10),
        "openai_model": (str, "gpt-4o-mini"),
        "github_action_schedule": (str, "0 19 * * *")
    }
    
    for field, (field_type, default_value) in default_fields.items():
        if field in defaults:
            try:
                field_type(defaults[field])
                print(f"  ✅ {field}: {defaults[field]}")
            except (ValueError, TypeError):
                print(f"  ❌ Invalid {field}: {defaults[field]} (should be {field_type.__name__})")
                return False
        else:
            print(f"  ⚠️  {field}: {default_value} (default)")
    
    # Validate GitHub access (optional)
    print(f"\n🔐 GitHub Access Validation:")
    if not validate_github_access(config):
        print("  ❌ GitHub access validation failed")
        print("  💡 Check your GH_TOKEN and organization permissions")
        return False
    
    print("\n🎉 Configuration validation completed successfully!")
    print("\nNext steps:")
    print("1. Set up your environment variables in .env file")
    print("2. Test with: DRY_RUN=1 ./run_local.sh")
    print("3. Run for a specific product: ./run_product.sh <shortname>")
    
    return True

if __name__ == "__main__":
    success = validate_config()
    sys.exit(0 if success else 1) 