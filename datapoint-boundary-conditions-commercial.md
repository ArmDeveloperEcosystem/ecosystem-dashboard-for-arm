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
- It can be singularly purchased
- It can be downloaded / installed by developers

## Examples

| ISV      					  | Products into Dashboard    | Rational | 
| ----------------------------------------------- | ----------- | -------- |
| [SAS](https://www.sas.com/en_us/home.html)      | SAS Viya    	| All SAS products are built from the SAS Viya software platform; this is the core package offering, which includes services built on top of SAS Viya (like SAS Data Engineering) |
| [Liferay](https://www.liferay.com/offerings)    | Liferay DXP, Liferay Commerce   | Liferay Commerce is built on Liferay DXP, but is a uniquely obtainable package from Liferay DXP and should be distinct. In addition|


### Detailed steps you can take:

1. **Identify Core Commercial Products**:
    - Visit the company's website, locate the section that lists their main commercial products. Focus on products marketed as standalone software solutions. Example on [Liferay](https://www.liferay.com/offerings).
2. **Identify Open-source product versions**:
    - Check if the ISV has community editions of any of its products to include for Open-source references on the dashboard. Example on [Liferay](https://www.liferay.com/downloads-community).
3. **Determine Compatibility with Arm Architecture**:
    - Check on Google: "SAS Viya Arm" or "SAS Viya aarch64".
    - Check the product docs for Arm architecture. Look for explicit mentions of supported platforms and architectures.
    - Visit the company's official GitHub page and search relevent repos for
    - Ask MS Copilot: "Does SAS Viya run on an Arm Linux server? Provide an answer with evidance from community discussions, release notes, announcement blogs, or similar."
    

## MS Copilot Prompt to help identify products:

I am creating a public website that lists all software packages that work on Arm Linux cloud servers, and am gathering the software packages now. To be included the package must be downloadedable / installable by developers, not just a SaaS offering. I need you to identify the core commercial products that developers would care works on Arm or not from this company: Liferay.

To help properly, you should output the following:
1. The company name I provided, and their main website
2. A list of their core commercial products that developers could buy and run on an Arm Linux cloud server.
3. Any online references to support if any of their identified core commercial products from step 2 support the Arm architecture (including documentation, community discussions, etc.)



#### MS Copilot Follow up questions
| Your concern      				           		| Prompt to help  | 
| --------------------------------------------------------------------- | --------------- |
| Not sure if software XYZ actually a unique package from ABC software. | Is XYZ a different, unique software package from ABC?    | 
| Not sure if software XYZ is hostable/downloadable by a dev, or SaaS.  | Can a developer download and host XYZ on their own cloud? |
| Not sure if software XYZ is hostable/downloadable by a dev, or SaaS.  | Are you sure each package can be run by a developer on their own cloud and not via SaaS? |
