#!/usr/bin/env python3
"""
EC Linter - Execution Card Validator
Version: 1.1.0
Data-driven validation with auto-fix suggestions
"""

import json
import re
import sys
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Colors for output
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'  # No Color

class ECLinter:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.content = ""
        self.errors = 0
        self.warnings = 0
        self.passed = 0
        self.fixes = []  # Auto-fix suggestions
        
        # Load rules
        self.rules_dir = Path(__file__).parent / "rules"
        self.structure_rules = self._load_json("structure.json")
        self.paths_rules = self._load_json("paths.json")
        self.semantic_rules = self._load_json("semantic.json")
        
    def _load_json(self, filename: str) -> dict:
        """Load JSON rule file"""
        try:
            with open(self.rules_dir / filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"{RED}[ERROR] Failed to load {filename}: {e}{NC}")
            return {}
    
    def load_file(self) -> bool:
        """Load EC file content"""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.content = f.read()
            return True
        except FileNotFoundError:
            print(f"{RED}[ERROR] File not found: {self.file_path}{NC}")
            return False
        except Exception as e:
            print(f"{RED}[ERROR] Failed to read file: {e}{NC}")
            return False
    
    def check_structure(self):
        """Check required sections and format"""
        print(f"\n{BLUE}Structure Check:{NC}")
        print("-" * 40)
        
        required_sections = self.structure_rules.get("required_sections", [])
        
        for section in required_sections:
            name = section.get("name", "")
            required = section.get("required", False)
            error_msg = section.get("error_message", f"Missing {name}")
            
            # Check for H2 section
            pattern = rf"^##\s+{re.escape(name)}"
            if re.search(pattern, self.content, re.MULTILINE):
                print(f"  {GREEN}[✓]{NC} {name} section found")
                self.passed += 1
            else:
                if required:
                    print(f"  {RED}[✗]{NC} {error_msg}")
                    print(f"       → Add: ## {name}")
                    self.errors += 1
                    
                    # Auto-fix suggestion
                    self.fixes.append({
                        "type": "missing_section",
                        "section": name,
                        "suggestion": f"\n## {name}\n\n[Add your {name.lower()} here]\n"
                    })
                else:
                    print(f"  {YELLOW}[!]{NC} Optional section {name} not found")
                    self.warnings += 1
        
        # Check for numbered steps (supports "1.", "Step 1:", "### Step 1:" formats)
        step_patterns = [
            r'^[0-9]+\.',                           # 1. Step name
            r'^Step\s+[0-9]+[:\.\)]',               # Step 1: or Step 1.
            r'^#{1,4}\s+Step\s+[0-9]+[:\.\)]',      # ### Step 1: (markdown headers)
        ]
        
        steps_found = any(re.search(p, self.content, re.MULTILINE | re.IGNORECASE) for p in step_patterns)
        
        if steps_found:
            print(f"  {GREEN}[✓]{NC} Numbered steps detected")
            self.passed += 1
        else:
            print(f"  {YELLOW}[!]{NC} No numbered steps found (1., Step 1:, or ### Step 1:)")
            self.warnings += 1
    
    def check_paths(self):
        """Check path validity and existence"""
        print(f"\n{BLUE}Path Check:{NC}")
        print("-" * 40)
        
        # Extract paths from content
        path_patterns = [
            r'`([^`]+(?:\/[^`]+)+)`',  # Code blocks with paths
            r'([a-zA-Z_][a-zA-Z0-9_]*\/[^\s\n]+)',  # word/path patterns
        ]
        
        found_paths = set()
        for pattern in path_patterns:
            matches = re.findall(pattern, self.content)
            found_paths.update(matches)
        
        if not found_paths:
            print(f"  {YELLOW}[!]{NC} No paths detected in file")
            self.warnings += 1
            return
        
        for path_str in found_paths:
            # Skip if it's just a word
            if '/' not in path_str and '\\' not in path_str:
                continue
            
            # Check if it's a template path ({{variable}}, {{timestamp}}, YYYY-MM-DD, etc.)
            if re.search(r'\{\{[^}]+\}\}', path_str) or \
               any(tpl in path_str for tpl in ['YYYY-MM-DD', 'XXX', 'HHMMSS']):
                print(f"  {YELLOW}[~]{NC} Template path (will be substituted): {path_str}")
                continue
            
            path = Path(path_str)
            
            # Check if absolute
            if path_str.startswith('/') or path_str.startswith('~'):
                print(f"  {YELLOW}[!]{NC} Use relative path: {path_str}")
                self.warnings += 1
                continue
            
            # Check existence
            if path.exists():
                if os.access(path, os.R_OK):
                    print(f"  {GREEN}[✓]{NC} Path exists: {path_str}")
                    self.passed += 1
                else:
                    print(f"  {RED}[✗]{NC} Path not readable: {path_str}")
                    self.errors += 1
            else:
                # Check if it's an output path
                if any(kw in path_str.lower() for kw in ['output', 'posts', 'drafts', 'results']):
                    print(f"  {YELLOW}[~]{NC} Output path (will create): {path_str}")
                else:
                    print(f"  {RED}[✗]{NC} Path does not exist: {path_str}")
                    self.errors += 1
    
    def scan_skills_directory(self):
        """Scan actual skills directory for validation"""
        skills_dirs = [
            Path.home() / ".openclaw" / "skills",
            Path.cwd() / "skills",
        ]
        
        available_skills = []
        for skills_dir in skills_dirs:
            if skills_dir.exists():
                available_skills.extend([d.name for d in skills_dir.iterdir() if d.is_dir()])
        
        return set(available_skills)
    
    def check_semantic(self):
        """Check semantic patterns and provide fixes"""
        print(f"\n{BLUE}Semantic Check:{NC}")
        print("-" * 40)
        
        patterns = self.semantic_rules.get("patterns", [])
        available_skills = self.scan_skills_directory()
        
        for pattern in patterns:
            name = pattern.get("name", "")
            keywords = pattern.get("keywords", [])
            required_deps = pattern.get("required_dependencies", [])
            warning_msg = pattern.get("warning_message", "")
            fix_snippet = pattern.get("fix_snippet", "")
            
            # Check if keywords exist
            found = any(re.search(rf'\b{re.escape(kw)}\b', self.content, re.IGNORECASE) for kw in keywords)
            
            if found:
                # Check if dependencies declared
                deps_found = any(dep.lower() in self.content.lower() for dep in required_deps)
                
                if required_deps and not deps_found:
                    print(f"  {YELLOW}[!]{NC} {warning_msg}")
                    self.warnings += 1
                    
                    if fix_snippet:
                        self.fixes.append({
                            "type": "missing_dependency",
                            "pattern": name,
                            "suggestion": fix_snippet
                        })
                else:
                    print(f"  {GREEN}[✓]{NC} {name}: OK")
                    self.passed += 1
                
                # Special check for skills
                if name == "skill_dependency":
                    for skill in required_deps:
                        if skill not in available_skills:
                            print(f"  {RED}[✗]{NC} Required skill not found: {skill}")
                            print(f"       Available: {', '.join(list(available_skills)[:5])}...")
                            self.errors += 1
    
    def print_fixes(self):
        """Print auto-fix suggestions"""
        if not self.fixes:
            return
        
        print(f"\n{BLUE}Auto-Fix Suggestions:{NC}")
        print("-" * 40)
        
        for i, fix in enumerate(self.fixes, 1):
            print(f"\n{i}. {fix['type'].replace('_', ' ').title()}")
            print(f"   {fix.get('pattern', fix.get('section', ''))}")
            print(f"\n   Suggested addition:")
            print(f"   {BLUE}```markdown{NC}")
            for line in fix['suggestion'].split('\n'):
                print(f"   {line}")
            print(f"   {BLUE}```{NC}")
    
    def run(self):
        """Run all checks"""
        print(f"{BLUE}EC Linter Report{NC}")
        print("=" * 40)
        print(f"File: {self.file_path}")
        print(f"Version: 1.1.0 (Data-Driven)")
        
        if not self.load_file():
            sys.exit(1)
        
        self.check_structure()
        self.check_paths()
        self.check_semantic()
        
        # Print fixes
        self.print_fixes()
        
        # Summary
        print(f"\n{BLUE}Summary{NC}")
        print("=" * 40)
        print(f"Passed:   {GREEN}{self.passed}{NC}")
        print(f"Warnings: {YELLOW}{self.warnings}{NC}")
        print(f"Errors:   {RED}{self.errors}{NC}")
        
        if self.errors == 0 and self.warnings == 0:
            print(f"\n{GREEN}[PASS]{NC} All checks passed! Ready to rename to EC-XXX.md")
            return 0
        elif self.errors == 0:
            print(f"\n{YELLOW}[WARN]{NC} Checks passed with warnings.")
            if self.fixes:
                print(f"       Apply the suggested fixes above.")
            return 0
        else:
            print(f"\n{RED}[FAIL]{NC} {self.errors} error(s) found.")
            print(f"\nNext Steps:")
            print(f"  1. Review and apply the fixes suggested above")
            print(f"  2. Run ec_linter again")
            print(f"  3. After [PASS], rename to EC-XXX-name.md")
            return 1


def main():
    if len(sys.argv) < 2:
        print("Usage: ec_linter.py <path/to/draft.md>")
        print("Example: ec_linter.py ExCard/temp_draft.md")
        sys.exit(1)
    
    file_path = sys.argv[1]
    linter = ECLinter(file_path)
    result = linter.run()
    sys.exit(result)


if __name__ == "__main__":
    main()
