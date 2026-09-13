const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("webapp_static/app.js", "utf8");
const start = source.indexOf("function priceCents(");
const end = source.indexOf("function quantity()", start);
const context = {};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
for (const [rate, quantity, packagePrice, expected] of [
  ["12",10,false,12], ["12",1000,false,1200], ["0.2",1,false,1],
  ["1.00001",10,false,2], ["31.80",1,true,3180],
  ["0.0002",1000000000,false,20000], ["19.999999",1,true,2000],
]) assert.equal(context.priceCents(rate,quantity,packagePrice),expected);
console.log("7 exact-price cases passed");
