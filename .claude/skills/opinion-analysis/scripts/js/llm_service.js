#!/usr/bin/env node
/**
 * llm_service.js - 长运行LLM服务进程
 *
 * 使用原生fetch调用API，绕过AI SDK兼容性检查
 * 保持LLM客户端连接，通过stdin/stdout通信
 *
 * 消息格式:
 *   输入: {"id": <唯一ID>, "prompt": <内容>, "model": <模型>, "maxTokens": <数量>}
 *   输出: {"id": <唯一ID>, "result": <响应内容>, "error": <错误信息>}
 *   结束信号: {"id": <唯一ID>, "end": true}  -> 退出进程
 */

import readline from 'readline';
import dotenv from 'dotenv';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// scripts/js -> scripts -> opinion-analysis -> skills -> .claude -> PROJECT_ROOT
const PROJECT_DIR = path.dirname(path.dirname(path.dirname(path.dirname(path.dirname(__dirname)))));

// 加载.env
const envPaths = [
  path.join(PROJECT_DIR, '.env'),
  path.join(PROJECT_DIR, '.env.local')
];
for (const p of envPaths) {
  if (fs.existsSync(p)) {
    dotenv.config({ path: p, override: false });
  }
}

// 配置
const API_KEY = process.env.LLM_API_KEY;
const BASE_URL = process.env.LLM_BASE_URL || 'https://api.openai.com/v1';
const DEFAULT_MODEL = process.env.LLM_MODEL;
const PROVIDER = process.env.LLM_PROVIDER || 'openai';  // API格式: openai/anthropic

if (!API_KEY) {
  process.stderr.write(JSON.stringify({ error: '需要 LLM_API_KEY 环境变量' }) + '\n');
  process.exit(1);
}

// 调用LLM（使用原生fetch）
async function callLlm(prompt, model, maxTokens) {
  const actualModel = model || DEFAULT_MODEL;
  if (!actualModel) {
    throw new Error('需要 model 或 LLM_MODEL');
  }

  // 根据LLM_PROVIDER判断API格式
  const isAnthropic = PROVIDER === 'anthropic';

  if (isAnthropic) {
    // Anthropic格式
    const response = await fetch(BASE_URL + '/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': API_KEY,
        'anthropic-version': '2023-06-01'
      },
      body: JSON.stringify({
        model: actualModel,
        max_tokens: maxTokens || 8192,
        messages: [{ role: 'user', content: prompt }]
      })
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API错误 ${response.status}: ${errorText}`);
    }

    const data = await response.json();
    // Anthropic/GLM格式：content数组可能包含thinking和text
    // 取text类型的内容，如果没有则取第一个
    const textContent = data.content?.find(c => c.type === 'text')?.text ||
                        data.content?.[0]?.text || '';
    return textContent;
  } else {
    // OpenAI兼容格式
    const chatUrl = BASE_URL.endsWith('/v1') ? BASE_URL + '/chat/completions' : BASE_URL + '/v1/chat/completions';

    const response = await fetch(chatUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${API_KEY}`
      },
      body: JSON.stringify({
        model: actualModel,
        max_tokens: maxTokens || 8192,
        messages: [{ role: 'user', content: prompt }],
        temperature: 0.3
      })
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API错误 ${response.status}: ${errorText}`);
    }

    const data = await response.json();
    return data.choices?.[0]?.message?.content || '';
  }
}

// 处理请求
async function handleRequest(data) {
  const { id, prompt, model, maxTokens, end } = data;

  // 结束信号
  if (end) {
    process.exit(0);
  }

  if (!prompt) {
    return { id, error: '需要 prompt' };
  }

  try {
    const result = await callLlm(prompt, model, maxTokens || 8192);
    return { id, result };
  } catch (error) {
    return { id, error: error.message };
  }
}

// 主循环
async function main() {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: false
  });

  // 每行一个JSON请求
  for await (const line of rl) {
    if (!line.trim()) continue;

    try {
      const data = JSON.parse(line);
      const response = await handleRequest(data);
      // 输出JSON响应（每行一个）
      process.stdout.write(JSON.stringify(response) + '\n');
    } catch (error) {
      // 解析错误也返回响应
      process.stdout.write(JSON.stringify({ id: null, error: 'JSON解析失败: ' + error.message }) + '\n');
    }
  }

  // stdin关闭时退出
  process.exit(0);
}

main().catch(error => {
  process.stderr.write(JSON.stringify({ error: error.message }) + '\n');
  process.exit(1);
});