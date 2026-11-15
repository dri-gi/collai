
clear;
clc;
close all;

%% COLLAI CONFIGURATION

PYTHON = "C:\Users\joshu\AppData\Local\Programs\Python\Python313\python.exe";

SCRIPT_DIR = fileparts(mfilename('fullpath'));
PYTHON_HELPER = fullfile(SCRIPT_DIR, "collai_fetch.py");

LOCAL_FILE = fullfile(tempdir, "collai_conversations.jsonl");

if ~isfile(PYTHON)
    error("Python 3.13 executable not found.");
end

if ~isfile(PYTHON_HELPER)
    error("collai_fetch.py must be in the same folder as this MATLAB script.");
end

%% PASSWORD PROMPT

answer = inputdlg( ...
    'Enter your UNO Q SSH password:', ...
    'CollAI Connection', [1 50]);

if isempty(answer)
    disp("Connection cancelled.");
    return;
end

setenv("COLLAI_PASSWORD", answer{1});
clear answer;

%% FIGURE

fig = figure('Name','CollAI Heart Monitor', ...
    'Color','k', ...
    'Position',[100 100 1150 750]);

ax1 = subplot(2,1,1);

pulseLine = animatedline(ax1, ...
    'Color',[0 1 0.4], ...
    'LineWidth',1.8);

title(ax1,'LIVE PULSE TREND','Color','w');
ylabel(ax1,'IR Sensor Value','Color','w');
grid(ax1,'on');

ax2 = subplot(2,1,2);

bpmLine = animatedline(ax2, ...
    'Color',[0.2 0.7 1], ...
    'LineWidth',2);

title(ax2,'HEART RATE TREND','Color','w');
xlabel(ax2,'Time (seconds)','Color','w');
ylabel(ax2,'BPM','Color','w');
grid(ax2,'on');

set([ax1 ax2], ...
    'Color','k', ...
    'XColor','w', ...
    'YColor','w');

%% START MONITOR

disp("=================================");
disp("       COLLAI HEART MONITOR");
disp("=================================");
disp("Connecting to UNO Q...");
disp("Downloading conversation history...");

lastError = "";

%% LIVE LOOP

while ishandle(fig)

    try

        %% DOWNLOAD JSONL USING PARAMIKO

        command = sprintf('"%s" "%s" "%s"', ...
            PYTHON, PYTHON_HELPER, LOCAL_FILE);

        [status, output] = system(command);

        if status ~= 0
            error("SSH transfer failed: %s", output);
        end

        %% READ JSONL

        if ~isfile(LOCAL_FILE)
            error("Conversation history file not found.");
        end

        lines = readlines(LOCAL_FILE);

        allTime = [];
        allIR = [];
        allBPM = [];

        %% EXTRACT ALL CONVERSATIONS

        for i = 1:length(lines)

            if strlength(strtrim(lines(i))) == 0
                continue;
            end

            record = jsondecode(char(lines(i)));

            if ~isfield(record,'heart_rate_readings')
                continue;
            end

            samples = record.heart_rate_readings;

            for j = 1:length(samples)

                sample = samples(j);

                if ~isfield(sample,'timestamp')
                    continue;
                end

                timestamp = double(sample.timestamp);

                irValue = NaN;
                bpmValue = NaN;

                if isfield(sample,'ir')
                    irValue = double(sample.ir);
                end

                if isfield(sample,'average_bpm')
                    bpmValue = double(sample.average_bpm);
                end

                if ~isfinite(bpmValue) || bpmValue <= 0

                    if isfield(sample,'bpm')
                        bpmValue = double(sample.bpm);
                    end

                end

                if ~isfinite(timestamp)
                    continue;
                end

                allTime(end+1) = timestamp;
                allIR(end+1) = irValue;
                allBPM(end+1) = bpmValue;

            end
        end

        %% CHECK DATA

        if isempty(allTime)

            title(ax1,'WAITING FOR SENSOR DATA','Color','w');
            drawnow;
            pause(3);
            continue;

        end

        %% SORT DATA

        [allTime,order] = sort(allTime);

        allIR = allIR(order);
        allBPM = allBPM(order);

        [allTime,uniqueIndex] = unique(allTime,'stable');

        allIR = allIR(uniqueIndex);
        allBPM = allBPM(uniqueIndex);

        %% RELATIVE TIME

        elapsed = allTime - allTime(1);

        %% UPDATE PULSE GRAPH

        clearpoints(pulseLine);

        validIR = isfinite(allIR);

        addpoints(pulseLine, ...
            elapsed(validIR), ...
            allIR(validIR));

        %% UPDATE BPM GRAPH

        clearpoints(bpmLine);

        validBPM = isfinite(allBPM) & allBPM > 0;

        addpoints(bpmLine, ...
            elapsed(validBPM), ...
            allBPM(validBPM));

        %% GRAPH WINDOW

        latestTime = max(elapsed);

        xlim(ax1,[max(0,latestTime-120),max(10,latestTime)]);
        xlim(ax2,[max(0,latestTime-120),max(10,latestTime)]);

        %% CURRENT BPM

        if any(validBPM)

            latestBPM = allBPM(find(validBPM,1,'last'));

            title(ax2,sprintf( ...
                'HEART RATE TREND | CURRENT: %.1f BPM', ...
                latestBPM),'Color','w');

        else

            title(ax2,'WAITING FOR VALID BPM','Color','w');

        end

        title(ax1,sprintf( ...
            'LIVE PULSE TREND | %d SAMPLES', ...
            length(allTime)),'Color','w');

        drawnow limitrate;

        if ~isempty(lastError)
            disp("Connection restored.");
            lastError = "";
        end

    catch ME

        if ~strcmp(lastError,ME.message)
            disp("COLLAI ERROR:");
            disp(ME.message);
            lastError = ME.message;
        end

    end

    pause(3);

end

%% CLEANUP

setenv("COLLAI_PASSWORD","");
disp("CollAI monitor stopped.");
