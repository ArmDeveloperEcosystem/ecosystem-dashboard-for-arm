import os, sys
from pathlib import Path
import yaml



def isCategoryValid(string, dictionary):
    # Check if any key in the dictionary matches the string
    for key in dictionary:
        if string in key:
            return True
    return False


if __name__ == "__main__":

    # Get the absolute path to this python file's directory
    script_dir = Path(__file__).parent.absolute()

    # Relative path to content from script, then tet absolute path to content by combining, and use Resolve to handle backwards".."
    category_data_yml_relative_path = Path('../data/category_data.yml')
    category_data_yaml = (script_dir / category_data_yml_relative_path).resolve()


    # content dirs
    opensource_relative_path = Path('../content/opensource_packages')
    opensource_absolute_path = (script_dir / opensource_relative_path).resolve()

    commercial_relative_path = Path('../content/commercial_packages')
    commercial_absolute_path = (script_dir / commercial_relative_path).resolve()
    
    content_directories = [opensource_absolute_path, commercial_absolute_path]




    # Read in category data into a dictionary, which maps {'category': 'group'}.
    with open(category_data_yaml, 'r') as file:
        data = yaml.safe_load(file)
        category_dict = data["subcategory_mapping"]
    


    # Loop over all packages
    invalid_packages = []
    valid_packages = []
    for content_directory in content_directories:
        for f in os.listdir(content_directory):
            if f.endswith(".md"):
                file_path_full = os.path.join(content_directory, f)
                with open(file_path_full, 'r') as file:
                    lines = file.readlines()
                    packages_type = 'Open source'
                    for line in lines:
                        if 'name:' in line:
                            packages_name = line.split('name:')[1].strip()
                        if 'category:' in line:
                            packages_category = line.split('category:')[1].strip()
                        if 'vendor:' in line:
                            packages_type = 'Commercial'

                # check if packages_category matches a key in category_dict
                is_valid = isCategoryValid(packages_category,category_dict)
                if is_valid:
                    try:
                        valid_packages.append({
                            "name": packages_name,
                            "category": packages_category,
                            "group": category_dict[packages_category]
                        })
                    except KeyError as e:
                        print("KEY ERROR, package category isn't in category dictionary. Check and try again.")
                        print("attempted: category_dict[packages_category]")
                        print('category_dict = ',category_dict)
                        print('packages_category =',packages_category)
                else:
                    invalid_packages.append({
                        "name": packages_name,
                        "file": f,   
                        "type": packages_type,                     
                        "category": packages_category,
                    })
    





    if invalid_packages:
        # Maximum width for columns
        max_package_name_width = max(len(max(invalid_packages, key=lambda x: len(x['name']))['name']), len('Package Name'))
        max_category_width = max(len(max(invalid_packages, key=lambda x: len(x['category']))['category']), len('Wrong Category'))
        max_type_width = max(len(max(invalid_packages, key=lambda x: len(x['type']))['type']), len('Type'))
        max_file_width = max(len(max(invalid_packages, key=lambda x: len(x['file']))['file']), len('File'))


        print("ERROR: The following packages have invalid categories:")
        print("   ","Package Name".ljust(max_package_name_width), "Wrong Category".ljust(max_category_width), "Type".ljust(max_type_width), "File".ljust(max_file_width))
        print("   ","-" * max_package_name_width, "-" * max_category_width, "-" * max_type_width, "-" * max_file_width)

        # Print data rows
        for package in invalid_packages:
            print("   ",package['name'].ljust(max_package_name_width), package['category'].ljust(max_category_width), package['type'].ljust(max_type_width), package['file'].ljust(max_file_width))
        sys.exit(1)


    else:
        # Maximum width for columns
        max_package_name_width = max(len(max(valid_packages, key=lambda x: len(x['name']))['name']), len('Package Name'))
        max_category_width = max(len(max(valid_packages, key=lambda x: len(x['category']))['category']), len('Category'))
        max_group_width = max(len(max(valid_packages, key=lambda x: len(x['group']))['group']), len('Group'))

        print("Success! Report of all packages:")
        print("   ","Package Name".ljust(max_package_name_width), "Group".ljust(max_group_width), "Category".ljust(max_category_width))
        print("   ","-" * max_package_name_width, "-" * max_group_width, "-" * max_category_width)

        for package in valid_packages:
            print("   ",package['name'].ljust(max_package_name_width), package['group'].ljust(max_group_width), package['category'].ljust(max_category_width))

        print("Success! See above report.")

            