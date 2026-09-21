import os
import re
import glob

pattern = re.compile(r'^(\s*)from datetime import (.*)UTC(.*)$', re.MULTILINE)

files = glob.glob(r"D:\Saurabh's Workflow\dograh\api\**\*.py", recursive=True)

for file in files:
    try:
        with open(file, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        continue
    
    def repl(m):
        indent = m.group(1)
        before_utc = m.group(2)
        after_utc = m.group(3)
        
        # reconstruct the remaining imports
        imports = (before_utc + " " + after_utc).split(',')
        imports = [x.strip() for x in imports if x.strip() and x.strip() != 'UTC']
        
        if 'timezone' not in imports:
            imports.append('timezone')
            
        imports_str = ", ".join(imports)
        
        return f"{indent}from datetime import {imports_str}\n{indent}UTC = timezone.utc"

    new_content, count = pattern.subn(repl, content)
    
    if count > 0:
        with open(file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Fixed {count} instances in {file}")
