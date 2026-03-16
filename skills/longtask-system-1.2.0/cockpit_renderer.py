#!/usr/bin/env python3
"""
LongTask Cockpit - 任务可视化驾驶舱
由 daemon 在状态更新时调用

Usage:
    python3 cockpit_renderer.py <task_file.json>
"""

import json
import sys
import os
from datetime import datetime


def render_cockpit(task_file):
    """读取任务文件并生成驾驶舱 HTML"""
    
    # 读取任务数据
    with open(task_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 提取核心数据
    task_name = data.get('task_id', 'Unknown Task')
    description = data.get('description', 'LongTask Mission')
    total_steps = data.get('total_steps', 0)
    
    steps = data.get('steps', [])
    done_steps = sum(1 for s in steps if s.get('status') == 'done')
    doing_steps = sum(1 for s in steps if s.get('status') == 'doing')
    
    progress = int((done_steps / total_steps * 100)) if total_steps > 0 else 0
    
    # 构建子任务列表 HTML
    rows_html = ""
    task_agent_id = data.get('agent_id', 'unknown')  # 任务级默认 agent
    for step in steps:
        status = step.get('status', 'pending')
        step_name = step.get('name', 'Unknown Step')
        agent_id = step.get('agent_id', task_agent_id)  # step 可覆盖，否则用任务级
        
        # 状态样式映射 - Pet Workshop 主题
        if status == 'done':
            status_icon = "🐱"
            card_bg = "bg-emerald-100 border-b-4 border-emerald-200"
            status_animation = ""
            badge = "Perfect! ✨"
        elif status == 'doing':
            status_icon = "🐕"
            card_bg = "bg-amber-50 border-b-4 border-amber-200"
            status_animation = "animate-digging"
            badge = "Digging... 🦴"
        elif status == 'failed':
            status_icon = "👻"
            card_bg = "bg-red-50 border-b-4 border-red-100"
            status_animation = ""
            badge = "Oh no! 💧"
        else:
            status_icon = "💤"
            card_bg = "bg-slate-50 opacity-60"
            status_animation = "animate-snooze"
            badge = "Zzz..."
        
        rows_html += f"""
        <div class="flex items-center gap-4 p-5 rounded-[2rem] transition-all duration-500 {card_bg} hover:translate-y-[-2px]">
            <div class="w-14 h-14 flex items-center justify-center rounded-2xl bg-white shadow-sm text-3xl {status_animation}">
                {status_icon}
            </div>
            <div class="flex-1 min-w-0">
                <div class="font-bold text-slate-700 text-base truncate">{step_name}</div>
                <div class="text-[11px] text-slate-400 mt-1 flex items-center gap-1">
                    <span class="bg-indigo-100 text-indigo-500 px-1.5 py-0.5 rounded-md font-bold italic">@{agent_id}</span>
                    <span>is on duty</span>
                </div>
            </div>
            <div class="text-[10px] font-bold px-3 py-1 rounded-full bg-white/50 text-slate-500 border border-white shadow-sm">
                {badge}
            </div>
        </div>
        """
    
    # 当前时间
    now = datetime.now()
    time_str = now.strftime("%H:%M:%S")
    date_str = now.strftime("%Y/%m/%d")
    
    # 完整的 UI 模板 - Pet Workshop 主题
    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pet Cockpit | {task_name}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@500;700&display=swap" rel="stylesheet">
    <style>
        body {{ 
            font-family: 'Quicksand', sans-serif; 
            background-color: #fef9f3;
            background-image: radial-gradient(#e5e7eb 1px, transparent 1px);
            background-size: 20px 20px;
        }}
        
        @keyframes digging {{
            0% {{ transform: rotate(-10deg); }}
            50% {{ transform: rotate(10deg) translateY(-2px); }}
            100% {{ transform: rotate(-10deg); }}
        }}
        .animate-digging {{ animation: digging 0.5s infinite ease-in-out; }}

        @keyframes snoozing {{
            0%, 100% {{ transform: scale(1); opacity: 0.6; }}
            50% {{ transform: scale(1.05); opacity: 1; }}
        }}
        .animate-snooze {{ animation: snoozing 2s infinite ease-in-out; }}

        .progress-fill {{
            transition: width 1.5s cubic-bezier(0.34, 1.56, 0.64, 1);
            background: linear-gradient(90deg, #fbbf24, #f59e0b);
        }}

        .floating {{ animation: float 3s infinite ease-in-out; }}
        @keyframes float {{
            0%, 100% {{ transform: translateY(0); }}
            50% {{ transform: translateY(-5px); }}
        }}
    </style>
</head>
<body class="p-4 md:p-8">
    <div class="max-w-lg mx-auto">
        <header class="mb-6 flex items-center justify-between bg-white/80 backdrop-blur-md p-4 rounded-[2rem] shadow-lg border-2 border-orange-100">
            <div class="flex items-center gap-3">
                <div class="text-4xl floating">🏠</div>
                <div>
                    <h1 class="text-xl font-bold text-orange-800">Pet Workshop</h1>
                    <p class="text-[10px] font-bold text-orange-400 uppercase tracking-[0.2em]">Helping you grow</p>
                </div>
            </div>
            <div class="px-4 py-1.5 bg-orange-100 text-orange-600 rounded-full text-xs font-bold border border-orange-200">
                🐾 {doing_steps} Pets Working
            </div>
        </header>

        <div class="bg-gradient-to-br from-orange-400 to-pink-500 p-8 rounded-[2.5rem] shadow-2xl shadow-orange-200 mb-8 text-white relative overflow-hidden border-4 border-white">
            <div class="relative z-10">
                <div class="text-[10px] font-bold opacity-80 uppercase tracking-widest mb-2">Today's Adventure</div>
                <div class="text-2xl font-bold mb-6 leading-tight">"{description}"</div>
                
                <div class="flex justify-between items-end mb-3">
                    <span class="text-xs font-bold bg-white/20 px-2 py-1 rounded-lg">Energy Level</span>
                    <span class="text-5xl font-black tracking-tighter">{progress}%</span>
                </div>
                <div class="w-full bg-black/10 h-5 rounded-full overflow-hidden p-1 border border-white/30">
                    <div class="progress-fill h-full rounded-full shadow-inner relative" style="width: {progress}%">
                        <div class="absolute right-0 top-0 bottom-0 w-2 bg-white/30"></div>
                    </div>
                </div>
                <div class="mt-4 text-xs font-medium opacity-90 flex justify-between">
                    <span>🍖 {done_steps} Treats earned</span>
                    <span>Total {total_steps} steps</span>
                </div>
            </div>
            <div class="absolute -right-4 -bottom-4 text-[12rem] opacity-10 rotate-12">🦴</div>
        </div>

        <div class="space-y-4">
            <h2 class="text-xs font-bold text-orange-300 uppercase tracking-widest mb-4 ml-4">
                Working Crew ({len(steps)})
            </h2>
            {rows_html}
        </div>

        <footer class="mt-10 text-center pb-10">
            <p class="text-[10px] font-bold text-orange-200 uppercase tracking-widest">
                Last Pat: {time_str} • {date_str}
            </p>
        </footer>
    </div>

    <script>
        setTimeout(() => location.reload(), 3000);
    </script>
</body>
</html>"""
    
    # 写入文件 (与任务文件同目录)
    output_path = os.path.join(os.path.dirname(task_file), 'cockpit.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(full_html)
    
    print(f"✅ Cockpit rendered: {output_path}")
    return output_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 cockpit_renderer.py <task_file.json>")
        sys.exit(1)
    
    task_file = sys.argv[1]
    if not os.path.exists(task_file):
        print(f"❌ Task file not found: {task_file}")
        sys.exit(1)
    
    try:
        output = render_cockpit(task_file)
        print(f"🐾 Open file://{output} in browser to view cockpit")
    except Exception as e:
        print(f"❌ Error rendering cockpit: {e}")
        sys.exit(1)
