import os, yaml

# LOAD ALL CATS
all_cats = ''
with open('data/all_categories.yml', 'r') as all_cat_file:
    all_cats = yaml.safe_load(all_cat_file)

# CREATE NEW ACTIVE_CATS LIST
content_dir = 'content/sw_database'
active_cats = []
for content_file in os.listdir(content_dir):
    if (content_file != ('_index.md')) and content_file.endswith('.md'):
        # OBTAIN CATEGORY FROM FILE
        cat = None
        with open(os.path.join(content_dir, content_file), 'r') as f:
            content_all = f.read()
            start = content_all.find('---')
            end = content_all.find('---', start + 3)
            content_metadata = content_all[start+3:end].strip()
            cat = yaml.safe_load(content_metadata).get('category')
        # ADD TO ACTIVE_CATS LIST IF NOT ALREADY PRESENT
        if cat in all_cats:
            if cat not in active_cats:
                active_cats.append(cat)

# SAVE ACTIVE_CATS LIST
with open('data/active_categories.yml', 'w') as active_cats_file:
    yaml.safe_dump(list(active_cats), active_cats_file, default_flow_style=False)

