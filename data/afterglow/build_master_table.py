import os
import csv
import glob

def main():
    # Get the directory of the current script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Find all CSV files in this directory
    csv_pattern = os.path.join(script_dir, "*.csv")
    csv_files = glob.glob(csv_pattern)
    
    # Exclude the master CSV from the list of source files
    master_filename = "afterglow_web_values_master.csv"
    master_path = os.path.join(script_dir, master_filename)
    csv_files = [f for f in csv_files if os.path.basename(f) != master_filename]
    
    print(f"Found {len(csv_files)} CSV files to merge: {[os.path.basename(f) for f in csv_files]}")
    
    # Read and merge data
    all_data = {}
    fieldnames = ["file", "Afterglow web zero_point", "Afterglow web err"]
    
    for file_path in sorted(csv_files):
        with open(file_path, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            # If the CSV has headers, read them and ensure we support any extra fields
            if reader.fieldnames:
                for field in reader.fieldnames:
                    field_stripped = field.strip()
                    if field_stripped not in fieldnames:
                        fieldnames.append(field_stripped)
            
            for row in reader:
                # Strip whitespace from keys and values
                cleaned_row = {k.strip(): v.strip() for k, v in row.items() if k is not None}
                file_key = cleaned_row.get("file")
                if not file_key:
                    continue
                
                # Check for duplicates or handle them
                if file_key in all_data:
                    existing = all_data[file_key]
                    if existing != cleaned_row:
                        print(f"Warning: Duplicate entry for file '{file_key}' with different values.")
                        print(f"  Existing: {existing}")
                        print(f"  New:      {cleaned_row}")
                all_data[file_key] = cleaned_row

    # Sort data by the 'file' column to ensure deterministic output
    sorted_keys = sorted(all_data.keys())
    sorted_rows = [all_data[k] for k in sorted_keys]
    
    # Write to the master CSV
    with open(master_path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted_rows:
            writer.writerow(row)
            
    print(f"Successfully constructed master table at: {master_path}")
    print(f"Total unique rows: {len(sorted_rows)}")

if __name__ == "__main__":
    main()
