pragma solidity >=0.8.0;

/**
 * @title NDEV-1004: neon-evm incorrectly handles the exit reason of the failed sub CALL, causing incorrect execution flow against the Ethereum specification
 */

contract ContractOne {
    event EventContractOne(string text);
    mapping(address => uint256) public addressBalances;

    function deposit() public payable {
        addressBalances[msg.sender] += msg.value;
    }

    function depositAndEmitEventAssertFalse() public payable {
        addressBalances[msg.sender] += msg.value;
        emit EventContractOne("depositAndEmitEvent");
        assert(false);
    }

    function depositAndEmitEventRevertWithRequire() public payable {
        addressBalances[msg.sender] += msg.value;
        emit EventContractOne("depositAndEmitEvent");
        require(!true);
    }

    function depositAndEmitEventRevert() public payable {
        addressBalances[msg.sender] += msg.value;
        emit EventContractOne("depositAndEmitEvent");
        revert("Revert Contract Two");
    }
}
