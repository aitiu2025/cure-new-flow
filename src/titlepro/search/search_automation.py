"""
Automated search script for Orange County Recorder website
This script will perform systematic searches for property records
"""

import time

# Define all search permutations to test
search_permutations = [
    # (name, party_type, description)
    ("Lau Casey", "Grantor/Grantee", "Last name first, both names"),
    ("Casey Lau", "Grantor/Grantee", "First name first, both names"),
    ("Lau Brandi", "Grantor/Grantee", "Last name first, Brandi"),
    ("Brandi Lau", "Grantor/Grantee", "First name first, Brandi"),
    ("Lau Casey", "Grantor", "Grantor only - Last name first"),
    ("Lau Casey", "Grantee", "Grantee only - Last name first"),
    ("Casey Lau", "Grantor", "Grantor only - First name first"),
    ("Casey Lau", "Grantee", "Grantee only - First name first"),
    ("Lau Brandi", "Grantor", "Grantor only - Brandi, Last name first"),
    ("Lau Brandi", "Grantee", "Grantee only - Brandi, Last name first"),
    ("Brandi Lau", "Grantor", "Grantor only - Brandi, First name first"),
    ("Brandi Lau", "Grantee", "Grantee only - Brandi, First name first"),
]

print("=" * 80)
print("ORANGE COUNTY RECORDER - SYSTEMATIC SEARCH PLAN")
print("=" * 80)
print("\nProperty: 8615 E Canyon Vista Dr, Anaheim Hills CA 92808")
print("Names: Casey Lau and Brandi Lau")
print("\nDate Range: 01/01/2010 - 1/8/2026")
print("\n" + "=" * 80)
print("SEARCH PERMUTATIONS TO EXECUTE:")
print("=" * 80)

for i, (name, party_type, description) in enumerate(search_permutations, 1):
    print(f"\n{i}. {description}")
    print(f"   Name: '{name}'")
    print(f"   Party Type: {party_type}")

print("\n" + "=" * 80)
print("SELENIUM AUTOMATION PATTERN:")
print("=" * 80)
print("""
For each search:
1. Navigate to https://cr.occlerkrecorder.gov/RecorderWorksInternet/
2. Click on "Name" tab
3. Select Party Type from dropdown (index 11)
4. Enter name in search field (index 13)
5. Set dates: Start 01/01/2010, End 1/8/2026
6. Click Search button (index 20)
7. Extract and log all results
8. Record document numbers, grantors, grantees, document types, and dates
9. Return to search form and repeat
""")

print("\n" + "=" * 80)
print("EXPECTED OUTPUTS:")
print("=" * 80)
print("""
- Document numbers matching the property
- Grantor/Grantee information for each document
- Document types (ASGT TRUST DEED, TRUST DEED, RECONVEYANCE, etc.)
- Recording dates
- Number of pages
- Comparison of results across different name permutations
""")

