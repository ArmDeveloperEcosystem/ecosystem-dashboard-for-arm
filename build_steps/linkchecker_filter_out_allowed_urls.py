import os, sys
from pathlib import Path

def csv_filtering(input_filename, output_filename, allow_list):
    # Crate a new CSV writing rows to the output if their URL is not in the allow-list.
    with open(input_filename, 'r') as infile:
        with open(output_filename, 'w') as outfile:
            for line in infile:
                url = line.split(';')[0]
                if url not in allow_list:
                    outfile.write(line)



if __name__ == "__main__":

    # Get the absolute path to this python file's directory
    script_dir = Path(__file__).parent.absolute()

    # Relative path to content from script, then tet absolute path to content by combining, and use Resolve to handle backwards".."
    allow_list_f_relative = Path("allow-list.txt")
    allow_list_f = (script_dir / allow_list_relative).resolve()

    csv_in_relative = Path("../linkchecker_raw_output.csv")
    csv_in = (script_dir / csv_in_relative).resolve()

    csv_out_relative = Path("../linkchecker_filtered_output.csv")
    csv_out = (script_dir / csv_out_relative).resolve()
    


    # Load the allow-list
    with open(allow_list_f, 'r') as f:
        allow_list = set(line.strip() for line in f)
    
    # Filter the CSV based on the allow-list
    csv_filtering(csv_in, csv_out, allow_list)