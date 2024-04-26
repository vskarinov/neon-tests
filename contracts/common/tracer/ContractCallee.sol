pragma solidity >=0.8.0;

contract ContractCallee {
    uint256 public parameter;
    address public sender;

    event EventContractCallee(string text);
    mapping(address => uint256) public addressBalances;

    function getBalance() public view returns (uint256) {
        return address(this).balance;
    }

    function deposit() public payable {
        addressBalances[msg.sender] += msg.value;
    }

    function setParam(uint256 _param) public payable {
        parameter = _param;
        sender = msg.sender;
    }

    function emitEvent() public payable {
        emit EventContractCallee("EmitEvent");
    }

    function emitEventAssertFalse() public payable {
        emit EventContractCallee("EmitEvent");
        assert(false);
    }

    function emitEventRevertWithRequire() public payable {
        emit EventContractCallee("EmitEvent");
        require(!true);
    }

    function emitEventRevert() public payable {
        emit EventContractCallee("EmitEvent");
        revert("Revert Contract");
    }

    function returnNumber(uint256 number) public pure returns (uint256) {
        return number;
    }

    function notSafeDivision(uint256 number, uint256 divider) public pure returns (uint256) {
        return number / divider;
    }
}
