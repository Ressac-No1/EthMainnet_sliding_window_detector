{
  structLogs: [],
  hashDict: [],
  SLoadRequest: {"contract": null, "location": null},
  hashRequest: {"key": null},
  txnFailed: false,
 
  step: function(log, db) {
    if (log.op.toString() == "REVERT") {
      this.txnFailed = true;
      this.structLogs.push({"op": "REVERT"});
      return;
    }
    if (this.txnFailed)
      return;
    if (log.getError()) {
      this.txnFailed = true;
      this.structLogs.push({"error": log.getError()});
      return;
    }

    if (this.SLoadRequest.contract && this.SLoadRequest.location) {
      newLog = {"op": "SLOAD", "contract": this.SLoadRequest.contract, "location": this.SLoadRequest.location, "value": log.stack.peek(0)};
      this.structLogs.push(newLog);
      this.SLoadRequest = {"contract": null, "location": null};
    }

    if (this.hashRequest.key) {
      this.hashDict.push({"key": this.hashRequest.key, "value": log.stack.peek(0)});
      this.hashRequest.key = null;
    }

    switch(log.op.toString()) {
      case "SSTORE":
        this.structLogs.push({"op": log.op.toString(), "contract": toHex(log.contract.getAddress()), "location": log.stack.peek(0), "newValue": log.stack.peek(1)});
        break;
      case "SLOAD":
        this.SLoadRequest = {"contract": toHex(log.contract.getAddress()), "location": log.stack.peek(0)};
        break;
      case "KECCAK256": case "SHA3":
        this.hashRequest.key = toHex(log.memory.slice(log.stack.peek(0), log.stack.peek(0) + log.stack.peek(1)));
        break;
    }
  },

  fault: function(log, db) {
    if (log.getError()) {
      this.txnFailed = true;
      this.structLogs.push({"error": log.getError()});
    }
  },

  result: function(ctx, db) {
    return {"gas": ctx.gasUsed, "failed": this.txnFailed, "structLogs": this.structLogs, "hashDict": this.hashDict};
  }
}
