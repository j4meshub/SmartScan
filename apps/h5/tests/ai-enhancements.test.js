import assert from "node:assert/strict";
import test from "node:test";

import {
  aiCandidateSummary,
  canDecideEnhancement,
  confidencePercent,
  createAiIdempotencyKey,
  latestEnhancement,
  shouldPollEnhancements,
  sourceVersionPreview,
} from "../ai-enhancements.js";

test("AI 幂等键使用安全随机数且符合接口格式", () => {
  const key = createAiIdempotencyKey("page/一", 3, {randomUUID:() => "12345678-1234-4234-8234-123456789abc"});
  assert.match(key, /^[A-Za-z0-9_.:-]{16,100}$/);
  assert.match(key, /\.v3\./);
  assert.throws(() => createAiIdempotencyKey("p", 0, {}), /ai_source_version_invalid/);
});

test("AI 候选仅提取面向用户的业务建议，不暴露 Provider 字段", () => {
  const enhancement = {
    provider_id:"internal-provider",
    model:"secret-model",
    candidate_result:{tasks:{
      classify_page:{label:"document",confidence:.91},
      detect_orientation:{rotation_degrees:90,confidence:.88},
      extract_title:{candidates:[{text:"次选",confidence:.6},{text:"会议纪要",confidence:.96}]},
      extract_page_number:{status:"detected",raw_label:"IV",normalized_number:4,confidence:.82},
    }},
  };
  assert.deepEqual(aiCandidateSummary(enhancement), [
    {kind:"classification",value:"document",confidence:.91},
    {kind:"orientation",value:90,confidence:.88},
    {kind:"title",value:"会议纪要",confidence:.96},
    {kind:"pageNumber",value:"IV",confidence:.82},
  ]);
  assert.doesNotMatch(JSON.stringify(aiCandidateSummary(enhancement)), /provider|secret-model/);
});

test("AI 状态选择、轮询、决定和基础版本预览遵守源版本", () => {
  const old={id:"old",status:"accepted",source_result_version:1};
  const current={id:"current",status:"processing",source_result_version:2};
  assert.equal(latestEnhancement([old,current],2), current);
  assert.equal(shouldPollEnhancements([old,current]), true);
  assert.equal(canDecideEnhancement({...current,status:"candidate_ready"},2), true);
  assert.equal(canDecideEnhancement({...current,status:"candidate_ready"},3), false);
  assert.equal(sourceVersionPreview(old,{active_result_version:2}),1);
  assert.equal(sourceVersionPreview(old,{active_result_version:1}),null);
  assert.equal(confidencePercent(.876),88);
});
