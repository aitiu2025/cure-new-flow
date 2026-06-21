# Orange County Recorder - Comprehensive Search Results
## Property: 8615 E Canyon Vista Dr, Anaheim Hills CA 92808

---

## KEY FINDING FROM SCREENSHOTS

The user-provided screenshots show that **both "Lau Casey" and "Lau Brandi" searches return the SAME 6 documents** when searched with Party Type: Grantor/Grantee and date range 01/01/2010 - 1/8/2026.

### Common Document Numbers Across Both Names (from screenshots):
1. **20120003487​19** - ASGT TRUST DEED - 6/20/2012 - 1 page
2. **20150003165​90** - ASGT TRUST DEED - 6/18/2015 - 1 page
3. **20160006154​80** - ASGT TRUST DEED - 12/6/2016 - 3 pages
4. **20160006154​81** - ASGT TRUST DEED - 12/6/2016 - 3 pages
5. **20170004368​0** - ASGT TRUST DEED - 10/19/2017 - 2 pages
6. **20190002468​78** - ASGT TRUST DEED - 7/11/2019 - 2 pages

---

## SEARCH RESULTS FROM CURRENT SESSION

### Search 1: "Lau Casey" - Party Type: All (Date Range: 1/9/2023 - 1/8/2026)
**Results:** 3 Result(s)

| Document Number | Grantors | Grantees | Document Type | Rec. Date | Pages |
|---|---|---|---|---|---|
| 20230000823​47 | LAU CASEY STEPHEN, LAU CASEY STEPHEN COTR | PARTNERS FEDERAL CREDIT UNION | TRUST DEED | 4/11/2023 | 9 |
| 20250001690​47 | LAU CASEY STEPHEN, LAU CASEY STEPHEN COTR | PARTNERS FEDERAL CREDIT UNION | TRUST DEED | 6/12/2025 | 9 |
| 20250001698​00 | LAU CASEY STEPHEN COTR | (blank) | RECONVEYANCE | 6/13/2025 | 1 |

**Analysis:** These are recent documents (2023-2025) with Partners Federal Credit Union. Different from the 6 documents shown in the screenshots.

---

## CRITICAL OBSERVATIONS

### 1. Name Format Matters
- The website appears to accept both "Last Name First" format (Lau Casey, Lau Brandi)
- Both names return the same set of 6 documents when using Grantor/Grantee party type with 2010-2026 date range

### 2. Party Type Variations
The screenshots show the search was performed with:
- **Party Type: Grantor/Grantee** (returns 6 results)
- **Allow Partial Match: True**
- **Date Range: 01/01/2010 - 1/8/2026**

### 3. Document Types Identified
- **ASGT TRUST DEED** (Assignment of Trust Deed) - 5 documents
- **TRUST DEED** - 1 document
- **RECONVEYANCE** - 1 document

### 4. Grantee Pattern
The screenshots show different grantee names in the "Grantor/Grantees" column:
- LAU CASEY STEPHEN (for Casey Lau search)
- LAU BRANDI HEATHER (for Brandi Lau search)

This suggests the system is matching on the full name including middle names.

---

## RECOMMENDED DOCUMENT NUMBERS FOR TITLEPRO247 QUERIES

Based on the screenshots provided, these are the document numbers that should be queried:

```
20120003487​19
20150003165​90
20160006154​80
20160006154​81
20170004368​0
20190002468​78
```

---

## SELENIUM AUTOMATION STRATEGY

### Step-by-Step Implementation Pattern:

```python
# 1. Navigate to recorder website
driver.get("https://cr.occlerkrecorder.gov/RecorderWorksInternet/")

# 2. Click Name tab
driver.find_element(By.XPATH, "//a[text()='Name']").click()

# 3. Select Party Type: Grantor/Grantee
party_type_dropdown = driver.find_element(By.ID, "MainContent_MainMenu1_SearchByName1_partytype")
party_type_dropdown.select_by_value("Grantor/Grantee")

# 4. Enter name
name_field = driver.find_element(By.ID, "MainContent_MainMenu1_SearchByName1_nameForSearch")
name_field.send_keys("Lau Casey")  # or "Lau Brandi"

# 5. Set dates
start_date = driver.find_element(By.ID, "start_date_field")
start_date.send_keys("01/01/2010")

end_date = driver.find_element(By.ID, "end_date_field")
end_date.send_keys("1/8/2026")

# 6. Click Search
search_button = driver.find_element(By.ID, "MainContent_MainMenu1_SearchByName1_btnSearch")
search_button.click()

# 7. Extract results
results = driver.find_elements(By.XPATH, "//table//tr[contains(@class, 'result-row')]")
for result in results:
    doc_number = result.find_element(By.XPATH, ".//td[1]").text
    grantors = result.find_element(By.XPATH, ".//td[2]").text
    grantees = result.find_element(By.XPATH, ".//td[3]").text
    doc_type = result.find_element(By.XPATH, ".//td[4]").text
    rec_date = result.find_element(By.XPATH, ".//td[5]").text
    pages = result.find_element(By.XPATH, ".//td[6]").text
    
    # Store in database or list
```

### Search Permutations to Test (in order of priority):

1. **"Lau Casey"** + Grantor/Grantee + 01/01/2010 - 1/8/2026 ✓ (6 results from screenshot)
2. **"Lau Brandi"** + Grantor/Grantee + 01/01/2010 - 1/8/2026 ✓ (6 results from screenshot)
3. **"Casey Lau"** + Grantor/Grantee + 01/01/2010 - 1/8/2026
4. **"Brandi Lau"** + Grantor/Grantee + 01/01/2010 - 1/8/2026
5. **"Lau Casey"** + Grantor only + 01/01/2010 - 1/8/2026
6. **"Lau Casey"** + Grantee only + 01/01/2010 - 1/8/2026
7. **"Lau Brandi"** + Grantor only + 01/01/2010 - 1/8/2026
8. **"Lau Brandi"** + Grantee only + 01/01/2010 - 1/8/2026

---

## NEXT STEPS

1. Continue with remaining search permutations to verify consistency
2. Verify that all 6 documents are specific to the property at 8615 E Canyon Vista Dr
3. Cross-reference document numbers with TitlePro247 database
4. Build Selenium script with error handling and result logging
5. Test at scale with multiple properties


---

## Search 2: "Casey Lau" - Party Type: All (Date Range: 1/9/2023 - 1/8/2026)
**Results:** 1 Result(s)

| Document Number | Grantors | Grantees | Document Type | Rec. Date | Pages |
|---|---|---|---|---|---|
| 20250002139​67 | CASEY LAUREL A TR | SCHOOLSFIRST FEDERAL CREDIT UNION | TRUST DEED | 8/1/2025 | 11 |

**Analysis:** This is a DIFFERENT person - "CASEY LAUREL A TR" (not "LAU CASEY STEPHEN"). This suggests the system is matching on partial name matches and returning different individuals. This is NOT the same Casey Lau from the property records.

**Key Insight:** The name format (first name first vs. last name first) AND the full name matter significantly. "Casey Lau" returns different results than "Lau Casey".



---

## Search 3: "Brandi Lau" - Party Type: All (Date Range: 1/9/2023 - 1/8/2026)
**Results:** 0 Result(s)

**Analysis:** No results found for "Brandi Lau" with Party Type All. This is different from "Lau Brandi" which returned 6 results in the screenshots. This confirms that name format is critical.

**Key Insight:** The system is sensitive to name order. "Brandi Lau" (first name first) does NOT return the same results as "Lau Brandi" (last name first).

