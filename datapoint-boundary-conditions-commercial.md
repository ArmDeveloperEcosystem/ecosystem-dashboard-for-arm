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
