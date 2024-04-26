pragma solidity >=0.8.0;

import "./ContractCallee.sol";

contract ChildContract {
    address public childAddr;

    constructor() payable {
        childAddr = address(this);
    }
}

contract ContractCaller {
    uint256 public parameter;
    address public sender;

    event EventContractCaller(string text);
    function deposit() public payable {}

    function setParamWithDelegateCall(
        address _contractCallee,
        uint256 _param
    ) public {
        (bool success, ) = _contractCallee.delegatecall(
            abi.encodeWithSignature("setParam(uint256)", _param)
        );
        require(success);
    }

    function setParamWithCallcode(
        address _contractCallee
    ) public {
        // callcode
        bytes4 sig = bytes4(keccak256("isSameAddress(address,address)")); //Function signature
        address a = msg.sender;
        assembly {
            let x := mload(0x40) //Find empty storage location using "free memory pointer"
            mstore(x, sig) //Place signature at beginning of empty storage
            mstore(add(x, 0x04), a) // first address parameter. just after signature
            mstore(add(x, 0x24), a) // 2nd address parameter - first padded. add 32 bytes (not 20 bytes)
            mstore(0x40, add(x, 0x64)) // this is missing in other examples. Set free pointer before function call. so it is used by called function.
            // new free pointer position after the output values of the called function.

            pop(callcode(
                5000, //5k gas
                _contractCallee, //To addr
                0, //No wei passed
                x, // Inputs are at location x
                0x44, //Inputs size two padded, so 68 bytes
                x, //Store output over input
                0x20
            )) //Output is 32 bytes long
        }
    }

    function getBalance() public view returns (uint256) {
        return address(this).balance;
    }

    function depositOnContractOne(address _contractCallee) public {
        bytes memory payload = abi.encodeWithSignature("deposit()");
        (bool success, ) = _contractCallee.call{value: 1, gas: 100000}(payload);
        require(!success);
    }

    function callContactRevertWithAssertFalse(
        address _contractCallee
    ) public returns (bool) {
        emit EventContractCaller("Emit ContractCaller Event");
        bytes memory payload = abi.encodeWithSignature(
            "emitEventAssertFalse()"
        );
        (bool success, ) = _contractCallee.call{value: 1, gas: 100000}(payload);
        return success;
    }

    function callContactRevert(address _contractCallee) public returns (bool) {
        emit EventContractCaller("Emit ContractCaller Event");
        bytes memory payload = abi.encodeWithSignature("emitEventRevert()");
        (bool success, ) = _contractCallee.call{value: 1, gas: 100000}(payload);
        return success;
    }

    function callContractRevertWithRequire(
        address _contractCallee
    ) public returns (bool) {
        emit EventContractCaller("Emit ContractCaller Event");
        bytes memory payload = abi.encodeWithSignature(
            "emitEventRevertWithRequire()"
        );
        (bool success, ) = _contractCallee.call{value: 1, gas: 100000}(payload);
        return success;
    }

    function getBalanceOfContractCallee(
        address _contractCallee
    ) public view returns (uint256) {
        ContractCallee _callee = ContractCallee(_contractCallee);
        uint256 balanceOfContractOne = _callee.getBalance();
        return balanceOfContractOne;
    }

    function emitEventAndGetBalanceOfContractCalleeWithEvents(
        address _contractCallee
    ) public returns (uint256) {
        emit EventContractCaller("Emit ContractCaller Event");
        ContractCallee _callee = ContractCallee(_contractCallee);
        _callee.emitEvent();
        uint256 balanceOfContractOne = _callee.getBalance();
        return balanceOfContractOne;
    }

    function emitEventAndCallContractCalleeWithEvent(
        address _contractCallee
    ) public {
        emit EventContractCaller("Emit ContractCaller Event");
        ContractCallee _callee = ContractCallee(_contractCallee);
        _callee.emitEvent();
    }

    function lowLevelCallContract(
        address _contractCallee
    ) public returns (bool) {
        bytes memory payload = abi.encodeWithSignature("returnNumber()", 1);
        (bool success, ) = _contractCallee.call(payload);
        return success;
    }

    function lowLevelCallContractWithEvents(address _contractCallee) public {
        emit EventContractCaller("Emit ContractCaller Event");
        bytes memory payload = abi.encodeWithSignature("returnNumber()", 1);
        _contractCallee.call(payload);
        bytes memory payloadEvent = abi.encodeWithSignature("emitEvent()");
        _contractCallee.call(payloadEvent);
    }

    function callNotSafeDivision(
        address _contractCallee
    ) public returns (bool) {
        bytes memory payload = abi.encodeWithSignature(
            "notSafeDivision(uint256,uint256)",
            1,
            0
        );
        (bool success, ) = _contractCallee.call(payload);
        return success;
    }

    function callTypeCreate2() public returns (address) {
        bytes32 salt = bytes32(0);
        address childContract = address(
            new ChildContract{salt: salt}()
        );
        return childContract;
    }
}
