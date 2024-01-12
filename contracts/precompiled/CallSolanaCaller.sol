pragma solidity >=0.7.0 <0.9.0;


import "../external/call_solana.sol";


contract CallSolanaCaller {

    CallSolana constant _callSolana = CallSolana(0xFF00000000000000000000000000000000000006);

    event LogBytes(bytes32 value);
    event LogStr(string value);

    function getNeonAddress(address addr) public returns (bytes32){
        bytes32 solanaAddr = _callSolana.getNeonAddress(addr);
        return solanaAddr;
    }

    function execute(uint64 lamports, bytes memory instruction) public {
        _callSolana.execute(lamports, instruction);

    }

    function getPayer() public returns (bytes32){
        bytes32 payer = _callSolana.getPayer();
        return payer;
    }


}