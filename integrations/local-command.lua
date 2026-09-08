-- Loaded as a private managed block by the Rust keyboard settings command.
-- No key events, window titles, or input state leave the compositor.
local function install(prefix, timeout)
  local tag = "remote-desktops-local-command"
  local armed, held, ready, command = nil, {}, false, nil
  local hint, deadline, release_timer, escape, trigger
  local modifiers = { [37]=true, [50]=true, [62]=true, [64]=true,
                      [105]=true, [108]=true, [133]=true, [134]=true }
  local function tagged(w)
    if not w or w.class ~= "com.moonlight_stream.Moonlight" then return false end
    for _, t in ipairs(w.tags or {}) do
      if t ~= tag and t:match("^remote%-desktops%-") then return true end
    end
    return false
  end
  local function mark(w, add)
    hl.dispatch(hl.dsp.window.tag({window="address:" .. w.address, tag=(add and "+" or "-") .. tag}))
  end
  local function finish()
    local old = armed
    armed, ready, command = nil, false, nil
    if deadline then deadline:set_enabled(false) end
    if release_timer then release_timer:set_enabled(false) end
    if escape then escape:set_enabled(false) end
    if hint then pcall(function() hint:dismiss() end); hint = nil end
    if old then pcall(function() mark(old, false) end) end
  end
  -- Remove a transient tag left by a previous configuration reload.
  for _, w in ipairs(hl.get_windows()) do mark(w, false) end
  hl.window_rule({match={class="com.moonlight_stream.Moonlight", tag=tag}, no_shortcuts_inhibit=true})
  deadline = hl.timer(finish, {timeout=timeout * 1000, type="repeat"})
  deadline:set_enabled(false)
  -- Keyboard events precede normal binding dispatch. Defer cleanup until the
  -- release dispatcher has run, including user bindings that fire on release.
  release_timer = hl.timer(finish, {timeout=1, type="repeat"})
  release_timer:set_enabled(false)
  local function activate()
    if armed then finish(); return end
    local w = hl.get_active_window()
    if not tagged(w) or hl.get_current_submap() ~= "" then return end
    armed, ready, command = w, next(held) == nil, nil
    mark(w, true)
    escape:set_enabled(true)
    deadline:set_enabled(true)
    hint = hl.notification.create({text="LOCAL COMMAND · " .. prefix .. " or Esc cancels\nUse your usual local shortcut. Remote control resumes when you release it.", timeout=timeout * 1000, icon="info"})
  end
  trigger = hl.bind(prefix, activate, {dont_inhibit=true, description="Remote Desktops: local-command prefix"})
  escape = hl.bind("Escape", function() release_timer:set_enabled(true) end,
      {dont_inhibit=true, description="Remote Desktops: cancel local command"})
  escape:set_enabled(false)
  local function focus(w)
    finish()
    held = {}
    trigger:set_enabled(tagged(w) and hl.get_current_submap() == "")
  end
  hl.on("window.active", focus)
  hl.on("window.update_rules", function(w)
    local active = hl.get_active_window()
    if active and active.address == w.address then trigger:set_enabled(tagged(w) and hl.get_current_submap() == "") end
  end)
  hl.on("window.close", function(w) if armed and w.address == armed.address then finish() end end)
  hl.on("keybinds.submap", function() finish(); trigger:set_enabled(tagged(hl.get_active_window()) and hl.get_current_submap() == "") end)
  hl.on("input.keyboard.key", function(code, _, state)
    if state == 0 then held[code] = nil else held[code] = true end
    if not armed then return end
    if not ready then ready = next(held) == nil; return end
    if state == 1 and not modifiers[code] and not command then command = code end
    if state == 0 and code == command then release_timer:set_enabled(true) end
  end)
  focus(hl.get_active_window())
  return {cleanup=finish}
end
_G.remote_desktops_prefix = install(PREFIX, TIMEOUT)
