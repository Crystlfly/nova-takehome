## How to run it
To run this project, you need to first install all of the required dependencies using pip, and then execute the harness script via the command line arguments provided in the instructions.

## What works
The robust document extraction pipeline using the LLM works exceptionally well, accurately parsing both PDF and Excel attachments to identify duplicate invoices effectively.

## What doesn't
The advanced volume rebate logic and complex quarterly threshold calculations have not been fully implemented yet, so those specific edge case evaluations are currently failing.

## The eval case that caught a bug
The duplicate invoice test case successfully caught a critical state persistence bug where processed invoice IDs were not being correctly committed to the state directory across restarted batches.
