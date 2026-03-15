#!/bin/bash
#
# EC Linter - Execution Card Validator
# Version: 1.0.0
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Initialize counters
ERRORS=0
WARNINGS=0
PASSED=0

# Check if file provided
if [ $# -eq 0 ]; then
    echo "Usage: ec_linter <path/to/draft.md>"
    echo "Example: ec_linter ExCard/temp_draft.md"
    exit 1
fi

FILE="$1"

# Check if file exists
if [ ! -f "$FILE" ]; then
    echo -e "${RED}[ERROR] File not found: $FILE${NC}"
    exit 1
fi

echo "EC Linter Report"
echo "================"
echo "File: $FILE"
echo ""

# ====================
# 1. Structure Check
# ====================
echo "Structure Check:"
echo "----------------"

# Check for Resource Dependencies
if grep -q "^## Resource Dependencies" "$FILE"; then
    echo -e "  ${GREEN}[✓]${NC} Resource Dependencies section found"
    ((PASSED++))
else
    echo -e "  ${RED}[✗]${NC} Missing Resource Dependencies section"
    echo "       → Add: ## Resource Dependencies"
    ((ERRORS++))
fi

# Check for Execution Workflow
if grep -q "^## Execution Workflow" "$FILE"; then
    echo -e "  ${GREEN}[✓]${NC} Execution Workflow section found"
    
    # Check for numbered steps
    if grep -q "^[0-9]\+\." "$FILE"; then
        echo -e "  ${GREEN}[✓]${NC} Numbered steps detected"
        ((PASSED++))
    else
        echo -e "  ${YELLOW}[!]${NC} No numbered steps found (1., 2., 3.)"
        echo "       → Use numbered list for sequential execution"
        ((WARNINGS++))
    fi
    ((PASSED++))
else
    echo -e "  ${RED}[✗]${NC} Missing Execution Workflow section"
    echo "       → Add: ## Execution Workflow"
    ((ERRORS++))
fi

# Check for Execution Conventions
if grep -q "^## Execution Conventions" "$FILE"; then
    echo -e "  ${GREEN}[✓]${NC} Execution Conventions section found"
    
    # Check for Input/Output subsections
    if grep -q "Input" "$FILE" || grep -q "Output" "$FILE"; then
        echo -e "  ${GREEN}[✓]${NC} I/O conventions defined"
        ((PASSED++))
    else
        echo -e "  ${YELLOW}[!]${NC} No explicit Input/Output conventions"
        ((WARNINGS++))
    fi
    ((PASSED++))
else
    echo -e "  ${RED}[✗]${NC} Missing Execution Conventions section"
    echo "       → Add: ## Execution Conventions"
    ((ERRORS++))
fi

echo ""

# ====================
# 2. Path Vitality Check
# ====================
echo "Path Check:"
echo "-----------"

# Extract paths from file (simple pattern matching)
PATHS=$(grep -oE '(\.\/|\~\/|[a-zA-Z_]+\/)[a-zA-Z0-9_\/\.-]+' "$FILE" | sort -u || true)

if [ -n "$PATHS" ]; then
    while IFS= read -r path; do
        # Skip if it's just a word, not a path
        if [[ ! "$path" =~ / ]]; then
            continue
        fi
        
        # Check if it's a template/example path
        if [[ "$path" =~ YYYY-MM-DD ]] || [[ "$path" =~ XXX ]]; then
            echo -e "  ${YELLOW}[~]${NC} Template path (needs substitution): $path"
            continue
        fi
        
        # Check if path exists
        if [ -e "$path" ]; then
            if [ -r "$path" ]; then
                echo -e "  ${GREEN}[✓]${NC} Path exists and readable: $path"
                ((PASSED++))
            else
                echo -e "  ${RED}[✗]${NC} Path exists but not readable: $path"
                ((ERRORS++))
            fi
        else
            # It's a future output path, that's OK
            if [[ "$path" =~ output ]] || [[ "$path" =~ posts/ ]] || [[ "$path" =~ drafts/ ]]; then
                echo -e "  ${YELLOW}[~]${NC} Output path (will be created): $path"
            else
                echo -e "  ${RED}[✗]${NC} Path does not exist: $path"
                ((ERRORS++))
            fi
        fi
    done <<< "$PATHS"
else
    echo -e "  ${YELLOW}[!]${NC} No paths detected in file"
    ((WARNINGS++))
fi

echo ""

# ====================
# 3. Semantic Check
# ====================
echo "Semantic Check:"
echo "---------------"

# Check for network-related keywords
if grep -qiE "(upload|post|send|api|http|request)" "$FILE"; then
    if ! grep -qiE "(skill|curl|wget|api|http)" "$FILE" | grep -qiE "resource|dependency"; then
        echo -e "  ${YELLOW}[!]${NC} Network operations detected but no network skill in dependencies"
        echo "       → Add network/API skill to Resource Dependencies"
        ((WARNINGS++))
    else
        echo -e "  ${GREEN}[✓]${NC} Network operations with declared dependencies"
        ((PASSED++))
    fi
fi

# Check for error handling
if grep -qiE "(error|fail|retry|exception|catch|if.*fail)" "$FILE"; then
    echo -e "  ${GREEN}[✓]${NC} Error handling detected"
    ((PASSED++))
else
    echo -e "  ${YELLOW}[!]${NC} No explicit error handling found"
    echo "       → Add error handling or retry logic"
    ((WARNINGS++))
fi

# Check for input validation
if grep -qiE "(check|validate|verify|if.*exist)" "$FILE"; then
    echo -e "  ${GREEN}[✓]${NC} Input validation detected"
    ((PASSED++))
else
    echo -e "  ${YELLOW}[!]${NC} No input validation steps found"
    ((WARNINGS++))
fi

echo ""

# ====================
# Summary
# ====================
echo "================"
echo "Summary"
echo "================"
echo "Passed:   $PASSED"
echo "Warnings: $WARNINGS"
echo "Errors:   $ERRORS"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}[PASS]${NC} All checks passed! Ready to rename to EC-XXX.md"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}[WARN]${NC} Checks passed with warnings. Review recommended."
    exit 0
else
    echo -e "${RED}[FAIL]${NC} $ERRORS error(s) found. Please fix before activating."
    echo ""
    echo "Next Steps:"
    echo "  1. Fix the errors listed above"
    echo "  2. Run ec_linter again"
    echo "  3. After [PASS], rename to EC-XXX-name.md"
    exit 1
fi
