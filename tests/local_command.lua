-- Isolated compositor harness: exercises the shipped Lua module without a desktop.
local callbacks, binds, timers, rules = {}, {}, {}, {}
local remote = {address="0x1", class="com.moonlight_stream.Moonlight", tags={"remote-desktops-spark"}}
local local_window = {address="0x2", class="terminal", tags={}}
local active, marked, submap, notifications = remote, false, "", 0
hl = {
  get_windows=function() return {remote, local_window} end,
  get_active_window=function() return active end,
  get_current_submap=function() return submap end,
  window_rule=function(rule) rules[#rules+1]=rule end,
  dsp={window={tag=function(args) return args end}},
  dispatch=function(args) if args.window == "address:0x1" then marked = args.tag:sub(1,1)=="+" end end,
  on=function(event, cb) callbacks[event]=cb end,
  bind=function(key, cb, opts)
    local b={callback=cb, options=opts, enabled=true}
    function b:set_enabled(v) self.enabled=v end
    binds[key]=b; return b
  end,
  timer=function(cb, opts)
    local t={callback=cb, options=opts, enabled=true}
    function t:set_enabled(v) self.enabled=v end
    timers[#timers+1]=t; return t
  end,
  notification={create=function()
    notifications=notifications+1
    return {dismiss=function() notifications=notifications-1 end}
  end}
}
PREFIX, TIMEOUT = "F12", 5
dofile("integrations/local-command.lua")
local function event(code, state) callbacks["input.keyboard.key"](code,0,state) end
local function fire(key) if binds[key].enabled then binds[key].callback() end end
local function tick(index) if timers[index].enabled then timers[index].callback() end end
local function arm()
  event(96,1); fire("F12"); event(96,0)
  assert(marked and notifications==1 and binds.Escape.enabled)
end
local function clean() assert(not marked and notifications==0 and not binds.Escape.enabled) end
assert(binds.F12.enabled and binds.F12.options.dont_inhibit)
assert(rules[1].no_shortcuts_inhibit)
-- Prefix release and modifier-only presses do not end the command.
arm(); event(133,1); event(50,1); assert(marked)
event(114,1); event(114,0); assert(marked) -- release-bound dispatch runs first
tick(2); clean(); event(50,0); event(133,0)
-- Reusable timers: more than one arm/timeout and command work.
for _=1,3 do arm(); tick(1); clean() end
arm(); event(9,1); fire("Escape"); event(9,0); tick(2); clean()
arm(); event(96,1); fire("F12"); event(96,0); clean()
-- Focus loss disables interception on other apps, including unmanaged Moonlight.
arm(); active=local_window; callbacks["window.active"](active); clean(); assert(not binds.F12.enabled)
active={address="0x3",class=remote.class,tags={}}; callbacks["window.active"](active); assert(not binds.F12.enabled)
active=remote; callbacks["window.active"](active); arm()
callbacks["window.close"](remote); clean()
-- A new managed tag on an already-focused window enables the prefix.
active={address="0x4",class=remote.class,tags={}}; callbacks["window.active"](active)
active.tags={"remote-desktops-other"}; callbacks["window.update_rules"](active); assert(binds.F12.enabled)
-- Respect local submaps; never reset a user's mode.
active=remote; callbacks["window.active"](active); arm(); submap="resize"
callbacks["keybinds.submap"](); clean(); assert(submap=="resize" and not binds.F12.enabled)
submap=""; callbacks["keybinds.submap"](); assert(binds.F12.enabled)
arm(); remote_desktops_prefix.cleanup(); clean()
print("local-command lifecycle passed")
