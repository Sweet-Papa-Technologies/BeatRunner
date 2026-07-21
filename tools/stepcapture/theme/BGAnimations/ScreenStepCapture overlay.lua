-- The runner screen. It is never meant to be seen for more than a frame or two:
-- it exists only to hold GAMESTATE setup between songs. It's kept plain black so
-- that if OBS is still rolling during the transition, the recording tail is clean
-- rather than a flash of theme UI.

local status = "starting…"

return Def.ActorFrame{
	OnCommand = function(self)
		-- Deferred by a frame: SetNewScreen() from inside the very first
		-- Init/On pass of a screen that is itself still being constructed is a
		-- reliable way to crash StepMania. Let this screen finish existing first.
		self:sleep(0.1):queuecommand("Advance")
	end,

	AdvanceCommand = function(self)
		if not StepCapture.Next() then
			status = "queue complete — you can close the game"
			self:GetChild("Status"):settext(status)
		end
	end,

	Def.Quad{
		InitCommand = function(self)
			self:FullScreen():diffuse(color("#000000"))
		end,
	},

	Def.BitmapText{
		Name = "Status",
		Font = "Common Normal",
		InitCommand = function(self)
			self:Center():diffuse(color("#FFFFFF")):settext(status)
		end,
	},
}
