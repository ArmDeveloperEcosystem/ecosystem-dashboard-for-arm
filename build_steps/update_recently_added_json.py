import os, sys
from pathlib import Path
import yaml
from datetime import datetime


# Get the absolute path to this python file's directory
script_dir = Path(__file__).parent.absolute()

# Relative path to content from script, then tet absolute path to content by combining, and use Resolve to handle backwards".."
opensource_relative_path = Path('../content/opensource_packages')
opensource_absolute_path = (script_dir / opensource_relative_path).resolve()

commercial_relative_path = Path('../content/commercial_packages')
commercial_absolute_path = (script_dir / commercial_relative_path).resolve()

# Same process for the YAML data file:
yaml_relative_path = Path('../data/recently_added_packages.yaml')
yaml_absolute_path = (script_dir / yaml_relative_path).resolve()




def get_all_package_metadata(package_path):
    with open(package_path, 'r') as f:
        content = f.read()
        # Get the metadata between '---' by splitting the content by '---' and grabbing the middle part
        metadata = content.split('---')[1]
        return yaml.safe_load(metadata)





# List to store recent content, in order
recent_content_with_all_metadata = []

content_directories = [opensource_absolute_path, commercial_absolute_path]

# Obtain all content and make them orderable by date
recent_content = []
for content_directory in content_directories:
    for f in os.listdir(content_directory):
        if f.endswith(".md"):
            file_path_full = os.path.join(content_directory, f)
            with open(file_path_full, 'r') as file:
                lines = file.readlines()
                # Initalize date string to keep track of dates, depending on data format
                date_str = None
                for line in lines:
                    if 'release_date_on_arm:' in line:
                        date_str = line.split('release_date_on_arm:')[1].strip()
                    elif 'release_date:' in line:
                        date_str = line.split('release_date:')[1].strip()
                    if date_str:
                        try:
                            date = datetime.strptime(date_str, '%d/%m/%Y')
                            recent_content.append({'file_path_full': file_path_full, 'date': date})
                            break
                        except ValueError:
                            print('ERROR---------------------')
                            print(f"Date format error in file: {file_path_full}")
                            print('----------------')
                            break

# Sort the content by date
recent_content.sort(key=lambda d: d['date'], reverse=True)

# Take the 5 most recent
recent_content = recent_content[:5]

# Get full metadata to fill out each file
for content in recent_content:
    content_metadata = get_all_package_metadata(content['file_path_full'])
    recent_content_with_all_metadata.append(content_metadata)

# Fill out full metadata for this content
print()
print('Adding these packages in order to data/recently_added_packages.yaml:')
for c in recent_content_with_all_metadata:
    print('   '+c['name'])
print()

# Write to YAML
with open(yaml_absolute_path, 'w', encoding='utf-8') as yaml_file:
    yaml.dump(recent_content_with_all_metadata, yaml_file, allow_unicode=True)
