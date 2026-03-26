import os, sys
from pathlib import Path
import yaml


def read_yaml_file(file_path):
    """
    Reads a YAML file and returns the parsed data.
    Returns None if the file is missing or invalid.
    """
    try:
        with open(file_path, 'r') as file:
            try:
                data = yaml.safe_load(file)
                return data
            except yaml.YAMLError as exc:
                print(f"ERROR: Error reading YAML file {file_path}: {exc}")
                return None
    except FileNotFoundError:
        print(f"ERROR: Input YAML file not found: {file_path}")
        return None
    except Exception as exc:
        print(f"ERROR: Unexpected error opening YAML file {file_path}: {exc}")
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

    # order alphabetically, but keep Miscallaneous at the end!
    sorted_group_list = sorted(
        [group for group in group_list if group != 'Miscellaneous']
    ) + (['Miscellaneous'] if 'Miscellaneous' in group_list else [])

    group_dict = {"groups": sorted_group_list}
    return group_dict


def group_description_list_simple(data):
    """
    Creates a dictionary simply listing out the main groups.
    """
    group_list = []
    for category_entry in data.get('category_list', []):
        group_name = category_entry.get('group')
        group_desc = category_entry.get('description')
        group_list.append({"name": group_name, "description": group_desc})

    # Sorting list of dictionaries by the 'name' key
    sorted_group_list = sorted(group_list, key=lambda x: x['name'])
    group_dict = {"groups_and_descriptions": sorted_group_list}
    return group_dict


def write_mapping_to_yaml(mapping, output_file):
    """
    Writes the subcategory-to-group mapping to a new YAML file.
    """
    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as outfile:
            yaml.dump(mapping, outfile, default_flow_style=False)
        return True
    except Exception as exc:
        print(f"ERROR: Failed writing output YAML file {output_file}: {exc}")
        return False


def update_category_mappings(input_file, output_file, label="mapping"):
    """
    Generates the category to subcategory mappings based on the category data.
    Returns True on success, False on failure.
    """
    print()
    print(f"=== Starting {label} ===")

    # Get the absolute path to this python file's directory
    script_dir = Path(__file__).parent.absolute()

    # Relative path to content from script, then get absolute path
    input_yaml_relative_path = Path(input_file)
    input_yaml_absolute_path = (script_dir / input_yaml_relative_path).resolve()

    # Same process for the output YAML data file
    output_yaml_relative_path = Path(output_file)
    output_yaml_absolute_path = (script_dir / output_yaml_relative_path).resolve()

    print(f"Script dir: {script_dir}")
    print(f"Input path: {input_yaml_absolute_path}")
    print(f"Input exists: {input_yaml_absolute_path.exists()}")
    print(f"Output path: {output_yaml_absolute_path}")
    print(f"Output parent dir: {output_yaml_absolute_path.parent}")
    print(f"Output parent exists before write: {output_yaml_absolute_path.parent.exists()}")

    category_raw_data = read_yaml_file(input_yaml_absolute_path)
    if category_raw_data is None:
        print(f"ERROR: Could not load input YAML for {label}")
        print(f"=== Failed {label} ===")
        return False

    if not isinstance(category_raw_data, dict):
        print(f"ERROR: YAML root is not a dictionary for {label}")
        print(f"Actual type: {type(category_raw_data)}")
        print(f"=== Failed {label} ===")
        return False

    if 'category_list' not in category_raw_data:
        print(f"ERROR: 'category_list' key missing in input YAML for {label}")
        print(f"Top-level keys: {list(category_raw_data.keys())}")
        print(f"=== Failed {label} ===")
        return False

    try:
        category_count = len(category_raw_data.get('category_list', []))
        print(f"Category groups found: {category_count}")

        subcategory_mapping_dict = subcategory_to_group_mapping(category_raw_data)
        group_dict = group_list_simple(category_raw_data)
        group_desc_dict = group_description_list_simple(category_raw_data)

        print(f"Subcategory mappings generated: {len(subcategory_mapping_dict.get('subcategory_mapping', {}))}")
        print(f"Groups generated: {len(group_dict.get('groups', []))}")
        print(f"Group descriptions generated: {len(group_desc_dict.get('groups_and_descriptions', []))}")

        # Merge the dictionaries
        final_category_dict = {**subcategory_mapping_dict, **group_dict, **group_desc_dict}

        write_ok = write_mapping_to_yaml(final_category_dict, output_yaml_absolute_path)
        if not write_ok:
            print(f"ERROR: Write step failed for {label}")
            print(f"=== Failed {label} ===")
            return False

        print(f"Output exists after write: {output_yaml_absolute_path.exists()}")
        if output_yaml_absolute_path.exists():
            try:
                print(f"Output file size: {output_yaml_absolute_path.stat().st_size} bytes")
            except Exception as exc:
                print(f"WARNING: Could not read output file size: {exc}")

        print("Category mapping success. Updated file:", output_yaml_absolute_path)
        print(f"=== Finished {label} ===")
        return True

    except Exception as exc:
        print(f"ERROR: Failed while processing {label}: {exc}")
        print(f"=== Failed {label} ===")
        return False


if __name__ == "__main__":
    linux_ok = update_category_mappings(
        '../package_category_list.yml',
        '../data/category_data.yml',
        label='linux category mapping'
    )

    windows_ok = update_category_mappings(
        '../package_category_list_windows.yml',
        '../data/category_data_windows.yml',
        label='windows category mapping'
    )

    print()
    print("=== Category mapping summary ===")
    print(f"Linux mapping success: {linux_ok}")
    print(f"Windows mapping success: {windows_ok}")

    if not linux_ok or not windows_ok:
        print("ERROR: One or more category mapping steps failed.")
        sys.exit(1)
