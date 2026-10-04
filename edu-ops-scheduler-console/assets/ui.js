(function () {
  const toast = () => {
    let node = document.querySelector('.toast');
    if (!node) {
      node = document.createElement('div');
      node.className = 'toast';
      document.body.appendChild(node);
    }
    return node;
  };

  const showToast = (message) => {
    const node = toast();
    node.textContent = message;
    node.classList.add('is-visible');
    window.clearTimeout(node._timer);
    node._timer = window.setTimeout(() => node.classList.remove('is-visible'), 2200);
  };

  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', async () => {
      const text = button.getAttribute('data-copy') || '';
      try {
        await navigator.clipboard.writeText(text);
        showToast('已复制到剪贴板');
      } catch (_err) {
        showToast(text);
      }
    });
  });

  document.querySelectorAll('[data-toast]').forEach((button) => {
    button.addEventListener('click', () => {
      const message = button.getAttribute('data-toast') || '操作已记录';
      if (button.hasAttribute('data-complete-label')) {
        button.textContent = button.getAttribute('data-complete-label');
        button.disabled = true;
      }
      showToast(message);
    });
  });

  document.querySelectorAll('[data-tabs]').forEach((group) => {
    const buttons = Array.from(group.querySelectorAll('[data-tab]'));
    const panels = Array.from(group.querySelectorAll('[data-tab-panel]'));
    buttons.forEach((button) => {
      button.addEventListener('click', () => {
        const target = button.getAttribute('data-tab');
        buttons.forEach((item) => item.classList.toggle('is-active', item === button));
        panels.forEach((panel) => {
          panel.hidden = panel.getAttribute('data-tab-panel') !== target;
        });
      });
    });
  });

  document.querySelectorAll('[data-filter-table]').forEach((input) => {
    const table = document.querySelector(input.getAttribute('data-filter-table'));
    if (!table) return;
    input.addEventListener('input', () => {
      const value = input.value.trim().toLowerCase();
      table.querySelectorAll('tbody tr').forEach((row) => {
        row.hidden = value && !row.textContent.toLowerCase().includes(value);
      });
    });
  });

  document.querySelectorAll('[data-severity-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      const target = button.getAttribute('data-severity-filter');
      document.querySelectorAll('[data-severity-filter]').forEach((item) => item.classList.remove('is-active'));
      button.classList.add('is-active');
      document.querySelectorAll('[data-severity]').forEach((row) => {
        row.hidden = target !== 'all' && row.getAttribute('data-severity') !== target;
      });
    });
  });

  document.querySelectorAll('[data-validate-file]').forEach((button) => {
    button.addEventListener('click', () => {
      const row = button.closest('tr');
      if (!row) return;
      const status = row.querySelector('[data-file-status]');
      if (status) {
        status.className = 'pill ok';
        status.textContent = '已校验';
      }
      button.textContent = '重新校验';
      showToast('字段、列名和指纹校验完成');
    });
  });

  document.querySelectorAll('[data-apply-plan]').forEach((button) => {
    button.addEventListener('click', () => {
      const row = button.closest('[data-plan-row]');
      if (!row) return;
      row.querySelector('[data-plan-state]').textContent = '已加入试跑队列';
      row.querySelector('[data-plan-state]').className = 'pill info';
      button.disabled = true;
      showToast('已写入诊断试跑队列');
    });
  });

  const nlForm = document.querySelector('[data-nl-form]');
  if (nlForm) {
    const input = nlForm.querySelector('[name="rule_text"]');
    const target = document.querySelector('[data-rule-draft]');
    nlForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const text = (input.value || '').trim();
      if (!text) {
        showToast('先输入一条规则');
        return;
      }
      const day = (text.match(/周[一二三四五六日天]|星期[一二三四五六日]/) || ['未识别日期'])[0].replace('周天', '周日');
      const slot = (text.match(/早自习|上午[1-4]|下午[1-4]|晚自习[12]?/) || ['待人工确认节次'])[0];
      const action = /必须|需要|固定|只能/.test(text) && !/不排|禁排|避免|不能/.test(text) ? '必须安排' : '禁排/避免';
      target.innerHTML = `
        <div class="rule-card">
          <div class="stack">
            <div class="split-line">
              <strong>${escapeHtml(action)} · ${escapeHtml(day)} ${escapeHtml(slot)}</strong>
              <span class="pill warn">待人工确认</span>
            </div>
            <p class="muted">${escapeHtml(text)}</p>
            <div class="toolbar">
              <span class="pill info">临时规则</span>
              <span class="pill">可映射后写入 rules.yaml 覆盖层</span>
            </div>
          </div>
          <button class="btn primary" type="button" data-confirm-draft>确认加入</button>
        </div>`;
      target.querySelector('[data-confirm-draft]').addEventListener('click', () => {
        target.querySelector('.pill.warn').className = 'pill ok';
        target.querySelector('.pill.ok').textContent = '已加入草稿';
        showToast('规则草稿已加入待保存队列');
      });
    });
  }

  const runButton = document.querySelector('[data-start-run]');
  if (runButton) {
    const fill = document.querySelector('[data-run-progress]');
    const label = document.querySelector('[data-run-label]');
    const log = document.querySelector('[data-run-log]');
    let timer = null;
    runButton.addEventListener('click', () => {
      let value = 35;
      runButton.disabled = true;
      label.textContent = '模型求解进行中';
      label.className = 'pill info';
      log.textContent = '[求解] 创建联合求解批次，时间上限 300 秒，并行数 8\n[校验] 求解前门禁通过，可以启动正式求解\n';
      timer = window.setInterval(() => {
        value = Math.min(100, value + 13);
        fill.style.setProperty('--value', `${value}%`);
        log.textContent += `[候选] 进度 ${value}%：已捕获可行方案，继续保留更优候选\n`;
        log.scrollTop = log.scrollHeight;
        if (value >= 100) {
          window.clearInterval(timer);
          label.textContent = '已完成，可查看结果交付';
          label.className = 'pill ok';
          runButton.disabled = false;
          runButton.textContent = '再次求解';
          showToast('求解批次已完成，可查看最优性缺口');
        }
      }, 520);
    });
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
})();
