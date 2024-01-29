# Summary
This data is sourced from Arm and our wide software ecosystem. While we make our best efforts to keep this dashboard accurate, there are no guarantees of data correctness due to the ever-evolving software landscape. For more details, continue reading this document for details about how package data is managed on this dashboard.

## Package testing requirements
Based on the listed datapoint criteria, this is a quick guide to how much a package needs to be validated before being added to the dashboard. 

For each package:
-	If Arm support is indicated via (1) mention in release notes, and/or (2) Arm binaries are provided for official download. *If one or both these conditions are met, no other formal testing/validation is needed*.
-	In any other case, Arm support must be validated. Validation is performed as follows:
	-	**Hardware:** Use an Arm Neoverse-N1 server; examples of acceptable servers are described below.
  	-	**OS:** Use one of the top three Linux distributions from the acceptable list described below.
   	-	**Process:** With the selected server and OS...
    		(1) Install the package via package manager or binary. Only build from source if that is the only option.
     		(2) If feasible, execute the package. For example a `$ package –version` is sufficient to prove it is installed correctly.
  
# Background Assumptions
Noting assumptions about the overall dashboard and all data contained within.

## Hardware
This lists the Arm IP in scope (and what is not) for this dashboard. It provides examples of commercial servers, that may be used during any package validation. 
-	Neoverse cores are the focus of this dashboard. The earliest core that must be supported is the Neoverse-N1. Examples of minimum hardware to support:
	-	AWS Graviton 2	(Neoverse-N1)
 	- 	Ampere Altra	(Neoverse-N1), which is used in GCP Tau T2A and Azure Dpsv5.
-	All Cortex cores are out of scope, from Cortex-A to Cortex-R to Cortex-M. Examples of hardware to not include:
	-	RaspberryPi 4 	(Cortex-A72x4)
 	-	ThunderX	(Armv8-A)
   
## OSes
This lists the OS and distributions that are in scope (and what is not) for this dashboard. It provides examples of distributions that may be used during any package validation. 
-	Linux OS only. Windows and Mac are both out of scope.
-	The following Linux distributions are considered in scope, and are prioritized for package validation in the below order. Packages are only validated to work against one or a few distributions, and there is no guarantee that all distributions support a package to the same degree.
	-	Ubuntu
 	-	RHEL
  	-	SUSE
	-	===
  	-	Fedora
  	-	Debian
  	-	CentOS
  	-	Arch Linux
  	-	openSUSE
  	-	Solus

# Specific Datapoint Rationale & Criteria
This section lists the (1) rationale behind including and (2) criteria for filling out data form fields in the Dashboard. The listed Criteria for each datapoint ensure consistency in data and a baseline for readers to understand the capabilities of a software package on Arm.

## Works on Arm 
Mandatory field

### Rationale
Indicates quickly to developers if this package Works on Arm, meaning they can feasibly obtain, setup, and use the package in a software project.

### Criteria
-	(Mandatory step) If the package can be obtained, set up, and executed on Arm hardware & OS defined above, then TRUE. Else, FALSE. See ‘Version: Supported Minimum’ for details on how this package is assessed to 'Work on Arm'.

## Version: Supported Minimum
Mandatory field

### Rationale
Indicates to developers what is the first version of the project that officially enabled support for Arm 64-bit hardware. 
This helps in two cases: (1) if the version they are currently using and comfortable with on x86 also works on Arm, and (2) if their environment is old or constrained to needing a non-recent package version, checking if the version they need still works on Arm.

### Criteria
At least one of these criteria must be met; check in this order:
1. Official support for arm64 or aarch64 is declared as part of this version’s release notes. Provide a link to release notes as proof under the proper data field.
2. Arm binaries are be provided as part of release alongside other architectures (typically x86). This is in the case of a package offering binary downloads online, having Arm as an option indicates Arm support.
3. If there are other reasons to believe Arm is supported (common knowledge, blogs, community notes, etc.), it must be tested to confirm. Validate that is works on Arm following the *Package testing requirements -> Process* section at the top of this file.

Note: If the found minimum supported version is officially deprecated, still list it as the minimum supported version -- always mention the earliest version that works on Arm. It is more beneficial for readers to have this earliest version for context. 

## Version: Recommended Minimum
Optional field

### Rationale
Indicates to developers that at this version and above, Arm support is high performance. Useful for setting expectations of developers that base support vs optimized are different. In most cases, Arm recommends developers to use the latest stable release for any project, as it will have latest and greatest support for Arm platforms. This datapoint is filled out when Arm has concrete data proving a notable change in performance starting from a particular version that is helpful for developers to know about.

### Criteria
- (Optional, Arm internal only. Not for external contributors to fill out) If Arm has internal data showing a step-change in performance starting from a particular version (that is between the minimum supported version and latest release), fill this datapoint.
  - In any other case, leave this datapoint blank.

## Support Caveats
Optional field

### Rationale
Indicates to developers any extra information needed to successfully obtain, set up, and run this package on the supported hardware and distributions. This could include, but is not limited to, package dependencies, different support for different Linux distributions, and different versions across different Linux distributions. In practice, these caveats are discovered via validating the minimum recommended version works on Arm by following the *Package testing requirements -> Process* section at the top of this document. 

Importantly, DO NOT include caveats that are non-Arm architecture specific. Only list dependencies & caveats that are Arm architecture specific. For example, if PyTorch needs the Arm Compute Library to work properly, it should be listed here as it is Arm architecture specific. 

### Criteria
-	If any Arm-specific caveats are needed based on findings from (1) release note information, (2) well-established knowledge, or (3) package validation through the *Package testing requirements -> Process* section, enumerate these caveats her in concise & understandable free text.


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

### Partner Resources - Criteria
- 	(Optional) Add one link to content from a trusted Arm partner. Source from the following locations in order of preference:
	- 	Arm Partner building or deploying Arm hardware – e.g. AWS, Azure, GCP/Google, Alibaba, Ampere, Marvell etc.
  	- 	ISV that provides commercial support for the project – e.g. F5 for nginx, Redis-labs for redis, Percona/Oracle for SQL etc.
  	- 	Other content from the broad Arm software ecosystem, that must be officially reviewed and approved by Arm. 

### Official Docs - Criteria
-	(Optional) Add one link to the official project documentation that specifically talks about the package on Arm. This is NOT to link to general documentation, and should be specifically about guidance to work with this package on Arm.


