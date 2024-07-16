# Summary
This data is sourced from Arm and our wide software ecosystem of Independant Software Vendors (ISVs). While we make our best efforts to keep this dashboard accurate, there are no guarantees of data correctness due to the ever-evolving software landscape. For more details, continue reading this document for details about how package data is managed on this dashboard.

## Package testing requirements
There are no specific testing requirements required for submission. Official support by ISV on aarch64 platforms is considered sufficient.
  
# Specific Datapoint Rationale & Criteria
This section lists the (1) rationale behind including and (2) criteria for filling out data form fields in the Dashboard. The listed Criteria for each datapoint ensure consistency in data and a baseline for readers to understand the capabilities of a commercial software package on Arm.

## Works on Arm 
Mandatory field

### Rationale
Indicates quickly to developers if this package Works on Arm, meaning they can feasibly obtain, setup, and use the package in a software project.

### Criteria
-	(Mandatory step) If the package can be obtained, set up, and executed on Arm hardware & OS defined above, then TRUE. Else, FALSE. See ‘Version: Supported Minimum’ for details on how this package is assessed to 'Work on Arm'.

## Release Date on Arm
Mandatory field

### Rationale
Indicates the earliest availability of official support for aarch64 by the ISV. 

### Criteria
- (Mandatory step) Must be sourced from a public statement from the vendor indicating official availability and support on aarch64. This may be an announcement, press-release or part of release notes or official documentation on the vendor/product website. 

## Getting Started Resources
Optional field

### Rationale
Provides resources to developers to install, deploy, test or measure performance specifically on Arm. Not intended to link to generic documentation. Look at each resource below for specific criteria to fill out each datapoint. All these datapoints are *optional*. When selecting between different sources to include, preference is given to performance optimization / performance measurements, then package deployment tutorials, then other types of content (like installation and otherwise). Note these should be **technical guides** for developers, not marketing content.

### Arm Resources - Criteria
-	(Optional) Add one link to content on an arm domain. This may include (but is not limited to):
	-	A learning path 		(learn.arm.com)
  	-	A blog 			        (community.arm.com)
  	-	Documentation/KBA 	(developer.arm.com)
  	-	A video 			      (on-demand.arm.com)	

### Vendor announcement - Criteria
- 	(Mandatory) Add a link to the official announcement from the vendor. This may be a press release or part of release notes or other documentation on the vendor website. 

### Official Docs - Criteria
-	(Optional) Add one link to the official project documentation that specifically talks about the package on Arm. This is NOT to link to general documentation, and should be specifically about guidance to work with this package on Arm.




# Guidelines for identifying the right ISV software package(s)

A unique software package from an ISV meets these criteria:
- It can be purchased from the ISV
- It can be downloaded / installed by developers
- It is not based on already listed ISV software packages

## Examples

| ISV      					  | Products    | Rational | 
| ----------------------------------------------- | ----------- | -------- |
| (SAS)[https://www.sas.com/en_us/home.html]      | SAS Viya    | All SAS products are built from the SAS Viya software platform; this is the core package offering, which includes all other products on top of SAS Viya (like SAS Data Engineering
| Liferay   					  | Text        |


1. Identify core commercial products
	-	Company website
 	-	Ask MS Copilot: "


**Goal**: Identify core commercial products from a given company and verify their compatibility with Arm architecture for listing on a software ecosystem dashboard.

**Instructions**: For the provided company, follow the steps below to list core commercial products and provide proof of Arm compatibility. Ensure to reference relevant documentation, online discussions mentioning Arm support, GitHub readme files or issues, etc.

### Steps to identify:

1. **Identify Core Commercial Products**:
    - Visit the company's official website and locate the section that lists their main commercial products. Focus on products marketed as standalone software solutions.
    - List the core products found.

2. **Determine Compatibility with Arm Architecture**:
    - Check the system requirements and product documentation on the official website to see if they mention support for Arm architecture. Look for explicit mentions of supported platforms and architectures.
    - Search the company's support forums, FAQs, or contact their support team to inquire about Arm compatibility if it's not clearly mentioned in the documentation.

3. **Examine GitHub Repositories**:
    - Visit the company's official GitHub page.
    - Identify repositories that are directly related to their core products. 
    - Check the README files and documentation within each repository for any mentions of Arm support. Review issues and discussions for additional insights.

4. **Review Community and Open Source Contributions**:
    - Look for community discussions, issues, or pull requests that mention Arm support. This can provide insights into unofficial support or ongoing efforts to enable compatibility.
    - Explore forks and clones of official repositories that might have been adapted for Arm.

5. **Vendor Communication**:
    - If compatibility information is not readily available, reach out to the vendor directly through their contact channels to confirm whether their products support Arm Linux servers.

**Example Company**: SAS

**Output**:
- A list of core commercial products offered by the company.
- Proof of Arm compatibility for each product, including references to:
  - Product documentation or data sheets
  - Relevant online discussions or forums
  - GitHub README files or issues
  - Direct communication from the vendor (if available)

**MS Copilot Prompt to help identify products**:

I am creating a public website that lists all software packages that work on Arm Linux cloud servers, and am gathering the software packages now. I need you to identify the core commercial products that developers would care works on Arm or not from this company: SAS.

To help properly, you should output the following:
1. The company name I provided, and their main website
2. A list of their core commercial products that developers could buy and run on an Arm Linux cloud server.
3. Any online references to support if any of their identified core commercial products from step 2 support the Arm architecture (including documentation, community discussions, etc.)


#### Follow up questions


| Your concern      				           		      | Prompt to help  | 
| --------------------------------------------------------------------------- | --------------- |
| Not sure if software XYZ actually a unique package from ABC software. | Is XYZ a unique package from ABC, or does XYZ use the ABC software to provide a different service?     | 
| Not sure if software XYZ is hostable/downloadable by a dev, or SaaS. | Can a developer download and host XYZ on their own cloud? |
