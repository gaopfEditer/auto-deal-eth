#!/usr/bin/env node
/**
 * 将 API 返回的问答字符串（含字面 \n）转为正常换行、有段落的 Markdown。
 *
 * 用法:
 *   node test/deal_md.js                    # 从 stdin 读，输出到 stdout
 *   node test/deal_md.js input.txt         # 从文件读，输出到 stdout
 *   node test/deal_md.js input.txt -o out.md
 *   node test/deal_md.js -o output.md      # stdin -> output.md
 */

const fs = require('fs');

function unescapeApiText(raw) {
  if (!raw) return raw;
  return raw
    .replace(/\\n/g, '\n')
    .replace(/\\t/g, '\t')
    .replace(/\\r/g, '\r');
}

function main() {
  const args = process.argv.slice(2);
  let inputPath = null;
  let outputPath = null;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '-o' || args[i] === '--output') {
      outputPath = args[++i];
    } else if (!args[i].startsWith('-')) {
      inputPath = args[i];
    }
  }

  const getInput = () => {
    if (inputPath) {
      return fs.readFileSync(inputPath, 'utf8');
    }
    return fs.readFileSync(0, 'utf8');
  };

  const raw = getInput();
  const formatted = unescapeApiText(raw);

  if (outputPath) {
    fs.writeFileSync(outputPath, formatted, 'utf8');
    process.stderr.write(`[OK] 已写入 ${outputPath}\n`);
  } else {
    process.stdout.write(formatted);
  }
}

main();
