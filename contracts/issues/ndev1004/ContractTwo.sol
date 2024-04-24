pragma solidity >=0.8.0;

contract ContractTwo {
    event EventContractTwo(string text);
    function deposit() public payable {}

    function getBalance() public view returns (uint256) {
        return address(this).balance;
    }

    function depositOnContractOne(address _contractOne) public {
        bytes memory payload = abi.encodeWithSignature("deposit()");
        (bool success, ) = _contractOne.call{value: 1, gas: 100000}(payload);
        require(!success);
    }

    function depositOnContractOneRevertWithAssertFalse(
        address _contractOne
    ) public returns (bool) {
        emit EventContractTwo("depositOnContractOneWithEvent");
        bytes memory payload = abi.encodeWithSignature(
            "depositAndEmitEventAssertFalse()"
        );
        (bool success, ) = _contractOne.call{value: 1, gas: 100000}(payload);
        return success;
    }

    function depositOnContractOneRevert(
        address _contractOne
    ) public returns (bool) {
        emit EventContractTwo("depositOnContractOneWithEvent");
        bytes memory payload = abi.encodeWithSignature(
            "depositAndEmitEventRevert()"
        );
        (bool success, ) = _contractOne.call{value: 1, gas: 100000}(payload);
        return success;
    }

    function depositOnContractOneRevertWithRequire(
        address _contractOne
    ) public returns (bool) {
        emit EventContractTwo("depositOnContractOneWithEvent");
        bytes memory payload = abi.encodeWithSignature(
            "depositAndEmitEventRevertWithRequire()"
        );
        (bool success, ) = _contractOne.call{value: 1, gas: 100000}(payload);
        return success;
    }
}
