/**
 * 主页 DOM 抓取：滚页加载全部作品，解析播放量/描述/日期。
 * 不依赖站内 API（会被频控），走真实渲染路径。
 * 用法：node harvest_author.js user1 user2 ...
 */
// 依赖：playwright-core。在装有该模块的项目目录下运行，例如
//   cd <项目> && node <skill>/scripts/harvest_author.js user1 user2
// 产出文件写在当前工作目录（cwd），不写进 skill 目录。
const fs = require('fs');
const path = require('path');

const OUT = path.join(process.cwd(), 'authors_v2.json');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const rnd = (a, b) => a + Math.random() * (b - a);

const parseCount = t => {
  if (!t) return 0;
  t = String(t).trim().replace(/\s/g, '').toUpperCase();
  const m = t.match(/^([\d.,]+)\s*([KMB])?$/);
  if (!m) return 0;
  let n = parseFloat(m[1].replace(/,/g, ''));
  if (m[2] === 'K') n *= 1e3;
  if (m[2] === 'M') n *= 1e6;
  if (m[2] === 'B') n *= 1e9;
  return Math.round(n);
};

const names = process.argv.slice(2);
if (!names.length) { console.log('用法: node harvest_author.js user1 user2 ...'); process.exit(1); }

(async () => {
  const { chromium } = require('playwright-core');   // 延迟到用时再 require，缺依赖不影响看用法
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const ctx = browser.contexts()[0];
  const page = ctx.pages().find(p => p.url().includes('tiktok.com')) || ctx.pages()[0];
  await page.bringToFront();

  const result = fs.existsSync(OUT) ? JSON.parse(fs.readFileSync(OUT, 'utf-8')) : {};

  for (const uname of names) {
    console.log(`\n===== @${uname} =====`);
    await page.goto(`https://www.tiktok.com/@${uname}?lang=vi-VN`, { waitUntil: 'domcontentloaded', timeout: 90000 }).catch(() => {});
    await sleep(rnd(5000, 7000));

    // 头部资料
    const head = await page.evaluate(() => {
      const q = s => { const e = document.querySelector(s); return e ? e.innerText.trim() : ''; };
      return {
        nick: q('[data-e2e=user-title]'),
        sub: q('[data-e2e=user-subtitle]'),
        bio: q('[data-e2e=user-bio]'),
        followers: q('[data-e2e=followers-count]'),
        likes: q('[data-e2e=likes-count]'),
        following: q('[data-e2e=following-count]'),
      };
    });
    console.log(`  昵称: ${head.nick} | ${head.sub}`);
    console.log(`  简介: ${(head.bio || '').replace(/\n/g, ' / ').slice(0, 150)}`);
    console.log(`  ${head.followers} 粉 | ${head.likes} 赞 | ${head.following} 关注`);

    // 滚页加载
    let lastCount = 0, stale = 0;
    for (let i = 0; i < 14; i++) {
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await sleep(rnd(1400, 2400));
      const n = await page.evaluate(() => document.querySelectorAll('[data-e2e=user-post-item]').length);
      if (n === lastCount) { stale++; if (stale >= 3) break; } else { stale = 0; lastCount = n; }
    }

    const vids = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll('[data-e2e=user-post-item]').forEach(el => {
        const a = el.querySelector('a');
        const href = a ? a.getAttribute('href') : '';
        const vid = (href || '').match(/video\/(\d+)/);
        const txt = el.innerText || '';
        const lines = txt.split('\n').map(s => s.trim()).filter(Boolean);
        const views = (el.querySelector('[data-e2e=video-views]') || {}).innerText || lines[lines.length - 1] || '';
        const img = el.querySelector('img');
        const alt = img ? (img.getAttribute('alt') || '') : '';
        out.push({ id: vid ? vid[1] : '', views: views, desc: alt.replace(/\s+/g, ' ').trim(), raw: lines.join(' | ').slice(0, 120) });
      });
      return out;
    });

    vids.forEach(v => v.play = parseCount(v.views));
    vids.sort((a, b) => b.play - a.play);
    const plays = vids.map(v => v.play).filter(x => x > 0).sort((a, b) => a - b);
    const median = plays.length ? plays[Math.floor(plays.length / 2)] : 0;
    console.log(`  抓到 ${vids.length} 条 | 中位播放 ${median.toLocaleString()} | 最高 ${(plays[plays.length - 1] || 0).toLocaleString()}`);
    vids.slice(0, 10).forEach((v, i) => {
      console.log(`   ${String(i + 1).padStart(2)}. ${String(v.play).padStart(10)} ${median ? '(' + (v.play / median).toFixed(1) + 'x)' : ''}  ${(v.desc || v.raw).slice(0, 110)}`);
    });

    result[uname] = { head, median, vids };
    await sleep(rnd(2000, 3500));
  }

  fs.writeFileSync(OUT, JSON.stringify(result, null, 2), 'utf-8');
  console.log(`\n→ ${OUT}`);
  await browser.close();
  process.exit(0);
})().catch(e => { console.log('FATAL', e.message); process.exit(1); });
