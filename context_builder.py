import os
import pathspec

def load_gitignore(gitignore_path=".gitignore"):
    """
    Reads the .gitignore file and creates a pathspec object to match against.
    Returns None if no .gitignore is found.
    """
    if not os.path.exists(gitignore_path):
        return None
        
    with open(gitignore_path, 'r', encoding='utf-8') as f:
        # Load the rules from the .gitignore file
        gitignore_rules = f.read()
    
    # Create the PathSpec object based on gitignore syntax
    return pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, gitignore_rules.splitlines())

def generate_project_context(output_file="project_context.txt"):
    """
    Scans the current directory, generates a file tree, and appends the content
    of ONLY .py files (respecting .gitignore rules) into a single output text file.
    """
    current_script = os.path.basename(__file__)
    
    # 1. Load gitignore rules
    spec = load_gitignore()
    
    # Initialize output strings
    tree_str = "Project Directory Structure:\n"
    tree_str += "============================\n"
    
    content_str = "File Contents:\n"
    content_str += "==============\n"

    # 2. Walk through the directory tree
    for root, dirs, files in os.walk("."):
        
        # Clean up the root path for pathspec (remove leading "./")
        clean_root = root.lstrip('./')
        
        # --- Filter Directories ---
        if spec:
            # We filter dirs in-place so os.walk doesn't dive into ignored folders
            dirs[:] = [d for d in dirs if not spec.match_file(os.path.join(clean_root, d) + '/')]
            
        # Add to Tree Structure
        level = root.replace(os.path.sep, '/').count('/')
        indent = ' ' * 4 * level
        tree_str += "{}{}/\n".format(indent, os.path.basename(root))
        
        subindent = ' ' * 4 * (level + 1)
        
        # --- Filter and Process Files ---
        for file in files:
            # Skip the output file and this script itself
            if file == output_file or file == current_script:
                continue
                
            file_path = os.path.join(root, file)
            clean_file_path = os.path.join(clean_root, file)

            # Check if file matches .gitignore rules
            if spec and spec.match_file(clean_file_path):
                continue # Skip ignored files

            # Add non-ignored file to the Tree Structure
            tree_str += "{}{}\n".format(subindent, file)

            # ONLY append contents if it's a .py file
            if file.endswith('.py'):
                content_str += f"\n--- START OF FILE: {file_path} ---\n"
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content_str += f.read()
                except Exception as e:
                    content_str += f"[Error reading file: {e}]"
                content_str += f"\n--- END OF FILE: {file_path} ---\n"

    tree_str += "\n\n"

    # 3. Write everything to the output file
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(tree_str)
            f.write(content_str)
        print(f"Success! Context saved to '{output_file}' (Respecting .gitignore, only .py contents included)")
    except Exception as e:
        print(f"Error writing output file: {e}")

if __name__ == "__main__":
    generate_project_context()
