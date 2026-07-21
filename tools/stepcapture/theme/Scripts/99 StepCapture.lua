-- 99 StepCapture.lua — the queue driver.
--
-- Loaded after the fallback theme's own scripts (filenames load in sort order,
-- and "99" sorts after "02 Branches.lua"), which is what lets us override
-- Branch.AfterGameplay below.

StepCapture = {
	queue = nil,   -- array of { dir = "/Songs/Pack/Song/", difficulty = "Challenge" }
	index = 0,     -- index of the song currently playing (1-based)
	server = "http://localhost:8777",
}

local QUEUE_PATH = "/Save/stepcapture/queue.tsv"

-- The queue is TSV, not JSON, on purpose: StepMania's Lua has no JSON decoder
-- in the base theme, and one line of gmatch beats vendoring one in.
function StepCapture.LoadQueue()
	if StepCapture.queue then return StepCapture.queue end

	local f = RageFileUtil.CreateRageFile()
	if not f:Open(QUEUE_PATH, 1) then
		f:destroy()
		Trace("[StepCapture] FATAL: cannot open " .. QUEUE_PATH)
		StepCapture.queue = {}
		return StepCapture.queue
	end
	local text = f:Read()
	f:Close()
	f:destroy()

	local q = {}
	for line in string.gmatch(text, "[^\r\n]+") do
		local dir, diff = string.match(line, "^(.-)\t(.+)$")
		if dir and diff then
			q[#q + 1] = { dir = dir, difficulty = diff }
		end
	end
	StepCapture.queue = q
	Trace("[StepCapture] loaded " .. #q .. " songs from the queue")
	return q
end

-- SONGMAN gives us Song objects; the queue gives us directories. Match them up.
function StepCapture.FindSong(dir)
	for _, song in ipairs(SONGMAN:GetAllSongs()) do
		if song:GetSongDir() == dir then return song end
	end
	return nil
end

function StepCapture.Notify(path, params, onDone)
	local url = StepCapture.server .. path
	if params then url = url .. "?" .. NETWORK:EncodeQueryParameters(params) end
	NETWORK:HttpRequest{
		url = url,
		method = "GET",
		connectTimeout = 5,
		transferTimeout = 30,
		onResponse = function(res)
			if onDone then onDone(res) end
		end,
	}
end

-- Find the dance-single chart at a given difficulty.
--
-- Deliberately does NOT call song:GetOneSteps(StepsType_Dance_Single, ...): the
-- StepsType enum globals are constructed at runtime and the exact casing is not
-- something worth guessing at (getting it wrong yields a bare "Expected StepsType;
-- got nil"). Iterating the song's real charts and comparing the values the game
-- itself hands back can't be spelled wrong.
function StepCapture.FindSteps(song, difficulty)
	local want = "Difficulty_" .. difficulty
	for _, steps in ipairs(song:GetAllSteps()) do
		local st = string.lower(tostring(steps:GetStepsType()))
		if steps:GetDifficulty() == want
		   and string.find(st, "dance", 1, true)
		   and string.find(st, "single", 1, true) then
			return steps
		end
	end
	return nil
end

-- Set up GAMESTATE for one song and drop straight into gameplay.
-- Returns false if the song/chart can't be resolved, so the runner can skip it.
function StepCapture.BeginSong(entry)
	local song = StepCapture.FindSong(entry.dir)
	if not song then
		Trace("[StepCapture] SKIP — no song at " .. entry.dir)
		return false
	end

	local steps = StepCapture.FindSteps(song, entry.difficulty)
	if not steps then
		Trace("[StepCapture] SKIP — no dance-single " .. entry.difficulty ..
		      " chart in " .. entry.dir)
		return false
	end

	-- Gameplay asserts if there is no style and no joined player. Reset first so
	-- each song starts from an identical state (no carry-over score/modifiers).
	GAMESTATE:Reset()
	-- Reset() leaves PlayMode invalid, and ScreenGameplay hard-crashes on it
	-- ("Invalid PlayMode: 7"). Normally ScreenSelectPlayMode sets this; we skip
	-- that whole flow, so we have to set it by hand.
	GAMESTATE:SetCurrentPlayMode('PlayMode_Regular')
	GAMESTATE:SetCurrentStyle("single")
	GAMESTATE:JoinPlayer(PLAYER_1)   -- also makes P1 the master player
	GAMESTATE:SetCurrentSong(song)
	GAMESTATE:SetPreferredSong(song)
	GAMESTATE:SetCurrentSteps(PLAYER_1, steps)

	-- The bot. "Autoplay" hits every note perfectly; "Cpu" deliberately misses
	-- (it's the arcade AI opponent) — do not confuse the two.
	PREFSMAN:SetPreference("AutoPlay", "Autoplay")

	Trace("[StepCapture] " .. StepCapture.index .. ": " .. song:GetDisplayFullTitle() ..
	      " [" .. entry.difficulty .. " " .. steps:GetMeter() .. "] — asking to record")

	-- Tell the recorder to roll, and only enter gameplay once it confirms. This
	-- is why the whole thing is an HTTP call and not a fire-and-forget: OBS needs
	-- to actually be recording before the first arrow moves.
	StepCapture.Notify("/song-start", {
		index = StepCapture.index,
		total = #StepCapture.queue,
		title = song:GetDisplayFullTitle(),
		dir = entry.dir,
		difficulty = entry.difficulty,
		meter = steps:GetMeter(),
	}, function(res)
		SCREENMAN:SetNewScreen("ScreenGameplay")
	end)

	return true
end

-- Advance to the next playable song. Called by the runner screen.
function StepCapture.Next()
	local q = StepCapture.LoadQueue()
	while true do
		StepCapture.index = StepCapture.index + 1
		if StepCapture.index > #q then
			Trace("[StepCapture] queue complete")
			StepCapture.Notify("/done", { total = #q })
			return false
		end
		if StepCapture.BeginSong(q[StepCapture.index]) then
			return true
		end
		-- unresolvable entry: loop and try the next one
	end
end

-- --------------------------------------------------------------------------
-- Gameplay exit hook.
--
-- Both _fallback and Simply Love define [ScreenGameplay] NextScreen as
-- "Branch.AfterGameplay()". Replacing that function is a far lighter touch than
-- overriding the metric, and it survives whatever the fallback theme does.
-- --------------------------------------------------------------------------
StepCapture.OriginalAfterGameplay = Branch.AfterGameplay

Branch.AfterGameplay = function()
	StepCapture.Notify("/song-end", { index = StepCapture.index })
	return "ScreenStepCapture"
end
