import os, yaml
from pathlib import Path


# Get the absolute path to this python file's directory
script_dir = Path(__file__).parent.absolute()

# Relative path to content from script, then tet absolute path to content by combining, and use Resolve to handle backwards".."
opensource_relative_path = Path('../content/opensource_packages')
opensource_absolute_path = (script_dir / opensource_relative_path).resolve()

commercial_relative_path = Path('../content/commercial_packages')
commercial_absolute_path = (script_dir / commercial_relative_path).resolve()

# Same process for the YAML data file:
yaml_relative_path = Path('../data/all_categories.yml')
yaml_absolute_path = (script_dir / yaml_relative_path).resolve()



print('Updating active categories...')

# LOAD ALL CATS
all_cats = ''
with open(yaml_absolute_path, 'r') as all_cat_file:
    all_cats = yaml.safe_load(all_cat_file)


# CREATE NEW ACTIVE_CATS LIST
content_directories = [opensource_absolute_path, commercial_absolute_path]

active_cats = []
for content_directory in content_directories:
    for content_file in os.listdir(content_directory):
        if (content_file != ('_index.md')) and content_file.endswith('.md'):
            # OBTAIN CATEGORY FROM FILE
            cat = None
            with open(os.path.join(content_directory, content_file), 'r') as f:
                for line in f:
                    if 'category:' in line:
                        cat = line.replace('category:','').strip()
                        break
            # ADD TO ACTIVE_CATS LIST IF NOT ALREADY PRESENT
            if cat in all_cats:
                if cat not in active_cats:
                    active_cats.append(cat)

# Order list alphabetically
active_cats = sorted(active_cats)     
for cat in active_cats:
    print('   '+cat)

# SAVE ACTIVE_CATS LIST
with open('data/active_categories.yml', 'w') as active_cats_file:
    yaml.safe_dump(list(active_cats), active_cats_file, default_flow_style=False)

