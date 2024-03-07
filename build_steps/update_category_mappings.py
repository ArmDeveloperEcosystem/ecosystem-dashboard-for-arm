import os, sys
from pathlib import Path
import yaml

def read_yaml_file(file_path):
    with open(file_path, 'r') as file:
        try:
            data = yaml.safe_load(file)
            return data
        except yaml.YAMLError as exc:
            print(f"Error reading YAML file: {exc}")
            return None

def subcategory_to_group_mapping(data):
    """
    Creates a dictionary mapping subcategory names to their corresponding group names.
    """
    subcategory_to_group = {}
    for category_entry in data.get('category_list', []):
        group_name = category_entry.get('group')
        for subcategory in category_entry.get('categories', []):
            subcategory_name = subcategory.get('name')
            subcategory_to_group[subcategory_name] = group_name

    subcategory_mapping = {"subcategory_mapping": subcategory_to_group}
    return subcategory_mapping

def group_list_simple(data):
    """
    Creates a dictionary simply listing out the main groups.
    """
    group_list = []
    for category_entry in data.get('category_list', []):
        group_name = category_entry.get('group')
        group_list.append(group_name)
    
    group_dict = {"groups": group_list}
    return group_dict

def write_mapping_to_yaml(mapping, output_file):
    """
    Writes the subcategory-to-group mapping to a new YAML file.
    """
    with open(output_file, 'w') as outfile:
        yaml.dump(mapping, outfile, default_flow_style=False)




if __name__ == "__main__":

    # Get the absolute path to this python file's directory
    script_dir = Path(__file__).parent.absolute()

    # Relative path to content from script, then tet absolute path to content by combining, and use Resolve to handle backwards".."
    input_yaml_relative_path = Path('../package_category_list.yml')
    input_yaml_absolute_path = (script_dir / input_yaml_relative_path).resolve()

    # Same process for the output YAML data file:
    output_yaml_relative_path = Path('../data/category_data.yml')
    output_yaml_absolute_path = (script_dir / output_yaml_relative_path).resolve()


    category_raw_data = read_yaml_file(input_yaml_absolute_path)
    
    subcategory_mapping_dict = subcategory_to_group_mapping(category_raw_data)
    group_dict = group_list_simple(category_raw_data)

    # Merge the dictionaries
    final_category_dict = {**subcategory_mapping_dict, **group_dict}

    write_mapping_to_yaml(final_category_dict, output_yaml_absolute_path)
    print("   Category mapping success. Updated file: ", output_yaml_absolute_path)
