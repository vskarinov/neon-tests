// SPDX-License-Identifier: MIT
pragma solidity ^0.8.5;

contract MemoryCopyExample {

    function copy(uint256 from, uint256 to, uint256 length) public pure returns (bytes memory) {
        bytes memory data = new bytes(length);
        bytes memory initData = "Hello, World!";

        assembly {
            mstore(add(from, 0x20), mload(add(initData, 0x20)))
            mcopy(add(data, 0x20), add(from, 0x20), length)
        }
        
        return data;
    }
}
