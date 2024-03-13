#!/bin/bash
# "Cleanup previous allure report"
rm -rf ./allure-report

# "Run OpenZeppelin tests"
python3 clickfile.py run oz --network=${NETWORK_NAME} --jobs=${FTS_JOBS_NUMBER} --amount=${REQUEST_AMOUNT} --users=${FTS_USERS_NUMBER}

# "Print OpenZeppelin report"
python3 clickfile.py oz report

# "Archive report"
ALLURE_RESULT_DIR=./allure-results
if [[ -d "$ALLURE_RESULT_DIR" ]]; then
    tar -czvf ./allure-reports.tar.gz $ALLURE_RESULT_DIR
fi

