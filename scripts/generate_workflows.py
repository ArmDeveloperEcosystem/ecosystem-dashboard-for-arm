import os
import re
import sys

# Configuration
CONTENT_DIR = 'content/opensource_packages'
WORKFLOW_DIR = '.github/workflows'
TEMPLATE_FILE = 'tests/template-package-test.yml'

def parse_frontmatter(file_path):
    """Parses simple YAML frontmatter from a markdown file."""
    metadata = {}
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract frontmatter between ---
    match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
    if match:
        frontmatter = match.group(1)
        for line in frontmatter.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                metadata[key.strip()] = value.strip()
    return metadata

def generate_workflow(slug, metadata, template_content):
    """Generates a workflow file content from the template."""
    package_name = metadata.get('name', slug.capitalize())
    category = metadata.get('category', 'Unknown')
    
    # Replace placeholders
    content = template_content.replace('<PACKAGE>', package_name)
    content = content.replace('<package>', slug)
    content = content.replace('REPLACE_ME', category) # For category/language placeholders if they match
    
    # Uncomment the push trigger section
    # The template has commented out push triggers. We need to uncomment them.
    # Pattern: #   push: ->   push:
    # We will do a simple replacement for the block we know exists in the template.
    
    # Naive uncommenting for the specific block structure in the template
    content = content.replace('# push:', 'push:')
    content = content.replace('#   branches:', '  branches:')
    content = content.replace('#     - main', '    - main')
    content = content.replace('#     - smoke_tests', '    - smoke_tests')
    content = content.replace('#   paths:', '  paths:')
    content = content.replace(f"#     - 'content/opensource_packages/{slug}.md'", f"    - 'content/opensource_packages/{slug}.md'")
    content = content.replace(f"#     - '.github/workflows/test-{slug}.yml'", f"    - '.github/workflows/test-{slug}.yml'")
    
    return content

def main():
    # Ensure directories exist
    if not os.path.exists(WORKFLOW_DIR):
        os.makedirs(WORKFLOW_DIR)
        
    # Read template
    try:
        with open(TEMPLATE_FILE, 'r', encoding='utf-8') as f:
            template_content = f.read()
    except FileNotFoundError:
        print(f"Error: Template file not found at {TEMPLATE_FILE}")
        sys.exit(1)

    created_count = 0
    skipped_count = 0
    errors = []

    # Iterate over markdown files
    for filename in os.listdir(CONTENT_DIR):
        if filename.endswith('.md'):
            file_path = os.path.join(CONTENT_DIR, filename)
            slug = filename[:-3].lower() # Remove .md and lowercase
            workflow_filename = f"test-{slug}.yml"
            workflow_path = os.path.join(WORKFLOW_DIR, workflow_filename)
            
            if os.path.exists(workflow_path):
                skipped_count += 1
                continue
            
            try:
                metadata = parse_frontmatter(file_path)
                workflow_content = generate_workflow(slug, metadata, template_content)
                
                with open(workflow_path, 'w', encoding='utf-8') as f:
                    f.write(workflow_content)
                
                created_count += 1
                # print(f"Created {workflow_filename}")
            except Exception as e:
                errors.append(f"{filename}: {str(e)}")

    print(f"\nSummary:")
    print(f"Total processed: {created_count + skipped_count}")
    print(f"Created: {created_count}")
    print(f"Skipped (already existed): {skipped_count}")
    
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for err in errors:
            print(err)

if __name__ == "__main__":
    main()
