//wait for document to be ready
$(document).ready(function() {

    // Screen orientation handling for mobile/tablet devices
    function handleOrientationChange() {
        // Small delay to ensure orientation change is complete
        setTimeout(function() {
            // Check if we're on a mobile/tablet device
            if (window.innerWidth <= 1024) {
                adjustCanvasSize();
                // Force redraw of the canvas to handle size changes
                if (steps.length > 0 && index >= 0) {
                    drawNewState(steps[index]);
                } else {
                    drawGrid({});
                }
            }
        }, 100);
    }

    // Listen for orientation changes
    window.addEventListener('orientationchange', handleOrientationChange);
    window.addEventListener('resize', handleOrientationChange);

    /* Board representation */
    const canvasBoard = document.getElementById("board");
    const ctxBoard = canvasBoard.getContext("2d");
    const gridSize = 14;
    const boardPath = './assets/Plateau_14x14.webp';
    const pieceBgPath = './assets/piece_bg.png';
    const offsetX = canvasBoard.width*0.0464; // horizontal distance between two centers 0.0562 for 11
    const offsetY = (offsetX * Math.sqrt(3)/2.0) + 0.5//- 0.2; // vertical distance between 2 centers -0.2 for 11
    const cellWidth = offsetX / 2.0; // width of the cell
    const cellSize = offsetX/Math.sqrt(3); //distance from center to a top
    // const initialX = canvasBoard.width*0.076; //for 11
    // const initialY = canvasBoard.width*0.0645;
    const initialX = canvasBoard.width*0.0475; //for 14
    const initialY = canvasBoard.width*0.043;

    // Load the piece images
    const pieceImages = {};
    // const pieceTypes = ['R', 'B'];
    const pieceColors = ['R','B'];
    // const playerColor = ['W', 'B'];
    for (const color of pieceColors) {
        const pieceImg = new Image();
        pieceImg.src = `./assets/${color}.png`;
        pieceImages[color] = pieceImg;
    }

    // background image for the pieces
    const pieceBgImg = new Image();
    pieceBgImg.src = pieceBgPath;

    const cellCoordinates = {};
    for (let row = 0; row < gridSize; row++) {
        for (let col = 0; col < gridSize; col++) {
            const cellCenterCoordinates = getCellCoordinates(row, col);
            cellCoordinates[`${row},${col}`] = cellCenterCoordinates;
        }
    }
    const firstPlayersData = {
        "R": {
            "name": "Player 1",
            "score": 0,
            "id": 1,
        },
        "B": {
            "name": "Player 2",
            "score": 0,
            "id": 2,
        }
            
    };

    // Load and draw the background board
    const boardImg = new Image();
    boardImg.src = boardPath;
    // wait for the image to be loaded before proceeding
    boardImg.onload = function() {
        adjustCanvasSize();
        drawGrid({});
        // Initialiser l'affichage des joueurs
        // Définir les noms initiaux par défaut
        window.initialPlayerNames = {
            player1: "Player 1",
            player2: "Player 2"
        };
        updatePlayerDisplay(firstPlayersData, "Player 1");
    }

    // Function to adjust canvas size based on screen size
    function adjustCanvasSize() {
        // Detect smartphone by screen dimensions (works in any orientation)
        const isSmartphone = (window.innerWidth <= 600) || 
                           (window.innerHeight <= 600 && window.innerWidth <= 900);
        
        if (isSmartphone) {
            // Smartphone: side-by-side layout with board and stacked players
            const availableWidth = Math.min(window.innerWidth * 0.7, window.innerWidth - 100);
            const availableHeight = Math.min(window.innerHeight * 0.6, window.innerHeight - 150);
            
            // Maintain aspect ratio (975:600)
            const aspectRatio = 975 / 600;
            let newWidth, newHeight;
            
            if (availableWidth / aspectRatio <= availableHeight) {
                newWidth = availableWidth;
                newHeight = availableWidth / aspectRatio;
            } else {
                newHeight = availableHeight;
                newWidth = availableHeight * aspectRatio;
            }
            
            // Ensure minimum size for smartphone playability
            const minWidth = Math.min(250, window.innerWidth * 0.6);
            const minHeight = minWidth / aspectRatio;
            
            newWidth = Math.max(newWidth, minWidth);
            newHeight = Math.max(newHeight, minHeight);
            
            canvasBoard.style.width = newWidth + 'px';
            canvasBoard.style.height = newHeight + 'px';
            canvasBoard.style.display = 'block';
            
        } else if (window.innerWidth <= 1024) {
            // Tablet: board above player panels
            const containerWidth = Math.min(window.innerWidth * 0.95, window.innerWidth - 20);
            const containerHeight = Math.min(window.innerHeight * 0.5, window.innerHeight - 200);
            
            // Maintain aspect ratio (975:600)
            const aspectRatio = 975 / 600;
            let newWidth, newHeight;
            
            if (containerWidth / aspectRatio <= containerHeight) {
                newWidth = containerWidth;
                newHeight = containerWidth / aspectRatio;
            } else {
                newHeight = containerHeight;
                newWidth = containerHeight * aspectRatio;
            }
            
            // Ensure minimum size for tablet playability
            const minWidth = Math.min(400, window.innerWidth * 0.8);
            const minHeight = minWidth / aspectRatio;
            
            newWidth = Math.max(newWidth, minWidth);
            newHeight = Math.max(newHeight, minHeight);
            
            canvasBoard.style.width = newWidth + 'px';
            canvasBoard.style.height = newHeight + 'px';
            canvasBoard.style.display = 'block';
            
        } else {
            // PC: keep original size
            canvasBoard.style.width = '975px';
            canvasBoard.style.height = '600px';
            canvasBoard.style.display = 'block';
        }
    }

    var steps = [];
    var index = -1;
    var play = false;
    var lastCellMouseOn = null;
    var lastPieceMouseOn = null;
    var active_player;
    var loop = null;
    var playersName = {
        "R": "Player 1",
        "B": "Player 2"
    };
    var socket = io({
        reconnection: false,
    });
    
    canvasBoard.addEventListener('mousemove', function(event) {
        const rect = canvasBoard.getBoundingClientRect();
        const scaleX = canvasBoard.width / rect.width;
        const scaleY = canvasBoard.height / rect.height;
        const mouseX = (event.clientX - rect.left) * scaleX;
        const mouseY = (event.clientY - rect.top) * scaleY;
        handleMouseMove(mouseX, mouseY);
    });

    //dbl click to avoid accidental clicks
    canvasBoard.addEventListener('dblclick', function(event) {
        const rect = canvasBoard.getBoundingClientRect();
        const scaleX = canvasBoard.width / rect.width;
        const scaleY = canvasBoard.height / rect.height;
        const mouseX = (event.clientX - rect.left) * scaleX;
        const mouseY = (event.clientY - rect.top) * scaleY;
        handleMouseClickBoard(mouseX, mouseY);
    });

    // Touch events for mobile devices
    let touchStartTime = 0;
    let touchStartPos = { x: 0, y: 0 };
    
    canvasBoard.addEventListener('touchstart', function(event) {
        event.preventDefault();
        touchStartTime = Date.now();
        const touch = event.touches[0];
        const rect = canvasBoard.getBoundingClientRect();
        touchStartPos.x = touch.clientX - rect.left;
        touchStartPos.y = touch.clientY - rect.top;
    });

    canvasBoard.addEventListener('touchend', function(event) {
        event.preventDefault();
        const touchDuration = Date.now() - touchStartTime;
        const touch = event.changedTouches[0];
        const rect = canvasBoard.getBoundingClientRect();
        const touchEndX = touch.clientX - rect.left;
        const touchEndY = touch.clientY - rect.top;
        
        // Check if it's a tap (not a drag) and duration is reasonable
        const distance = Math.sqrt(
            Math.pow(touchEndX - touchStartPos.x, 2) + 
            Math.pow(touchEndY - touchStartPos.y, 2)
        );
        
        if (touchDuration < 500 && distance < 20) {
            const scaleX = canvasBoard.width / rect.width;
            const scaleY = canvasBoard.height / rect.height;
            const mouseX = touchEndX * scaleX;
            const mouseY = touchEndY * scaleY;
            handleMouseClickBoard(mouseX, mouseY);
        }
    });

    canvasBoard.addEventListener('touchmove', function(event) {
        event.preventDefault();
        const touch = event.touches[0];
        const rect = canvasBoard.getBoundingClientRect();
        const scaleX = canvasBoard.width / rect.width;
        const scaleY = canvasBoard.height / rect.height;
        const mouseX = (touch.clientX - rect.left) * scaleX;
        const mouseY = (touch.clientY - rect.top) * scaleY;
        handleMouseMove(mouseX, mouseY);
    });

    function handleMouseClickBoard(mouseX, mouseY) {
        const cell = isMouseOnCell(mouseX, mouseY);
        if (cell !== null) {
            socket.emit("interact", JSON.stringify({
                "piece": Object.entries(playersName).find(([color, playerName]) => playerName === active_player)?.[0] || null,
                "position": cell,
            }));
            selectedPiece = null;
            lastPieceMouseOn = null;
            lastCellMouseOn = null;
        }
    }

    function handleMouseMove(mouseX, mouseY) {
        const cell = isMouseOnCell(mouseX, mouseY);
        if (cell !== null && (lastCellMouseOn === null || cell.toString() !== lastCellMouseOn.toString())) {
            canvasBoard.style.cursor = "pointer";
            ctxBoard.clearRect(0, 0, canvasBoard.width, canvasBoard.height);
            drawGrid(steps[index] ? steps[index].env : {});
            placePiece(cell[0], cell[1], pieceBgImg);
            lastCellMouseOn = cell;
        }else if(cell === null){
            canvasBoard.style.cursor = "default";
            ctxBoard.clearRect(0, 0, canvasBoard.width, canvasBoard.height);
            //Redraw to erase the piece background
            drawGrid(steps[index] ? steps[index].env : {});
        }
    }

    function isMouseOnCell(mouseX, mouseY){
        // Debug logging for mobile devices
        if (window.innerWidth <= 1024) {
            console.log(`Mouse coordinates: (${mouseX.toFixed(2)}, ${mouseY.toFixed(2)})`);
            console.log(`Canvas actual size: ${canvasBoard.width}x${canvasBoard.height}`);
            console.log(`Canvas display size: ${canvasBoard.offsetWidth}x${canvasBoard.offsetHeight}`);
        }
        
        //Compute hexagonal grid coordinates
        const q = (Math.sqrt(3)/3.0 * (mouseX - initialX) - 1/3.0 * (mouseY - initialY)) / cellSize;
        const r = (2/3.0 * (mouseY - initialY)) / cellSize;

        // Convert to cube coordinates
        const x = q;
        const z = r;
        const y = -x - z;

        // Round each
        let rx = Math.round(x);
        let ry = Math.round(y);
        let rz = Math.round(z);

        // Calculate deltas
        const dx = Math.abs(rx - x);
        const dy = Math.abs(ry - y);
        const dz = Math.abs(rz - z);

        // Fix the coordinate with the largest delta
        if (dx > dy && dx > dz) {
            rx = -ry - rz;
        } else if (dy > dz) {
            ry = -rx - rz;
        } else {
            rz = -rx - ry;
        }

        // Convert back to axial
        const finalQ = rx;
        const finalR = rz;

        // Debug logging for mobile devices
        if (window.innerWidth <= 1024) {
            console.log(`Calculated cell: (${finalR}, ${finalQ})`);
        }

        if (finalR < 0 || finalR >= gridSize || finalQ < 0 || finalQ >= gridSize) {
            return null;
        }
        return [finalR, finalQ];
    }

    
    $("#loadJson").on("change", function() {
        const file = this.files[0];
        const reader = new FileReader();
        reader.onload = function(e) {
            const json = JSON.parse(e.target.result);
            let gameData = [];

            for (const step of json) {
                const players_info = convertToPlayerInfo(step.players, step.scores);
                gameData.push({"env": step.rep.env, "players":players_info, "active_player": step.active_player.name});
            }
            steps = gameData;
            index = 0;
            drawNewState(steps[index]);
        }
        reader.readAsText(file);
    });


    $('#time').on('change', function() {
        play = false;
        $("#play").click();
    });

    $("#play").click(function() {
        play = true;
        
        if (loop) {
            clearInterval(loop);
        }
        
        loop = setInterval(function() {
            if (play) {
                if (index < steps.length - 1) {
                    index++;
                    drawNewState(steps[index]);
                } else {
                    play = false;
                    clearInterval(loop);
                }
            } else {
                clearInterval(loop);
            }
        }, $("#time").attr("max") - $("#time").val());
    });

    $("#stop").click(function() {
        play = false;
    });

    $("#reset").click(function() {
        index = 0;
        drawNewState(steps[index]);
    });
    $("#next").click(function() {
        if (index < steps.length - 1) {
            index++;
            drawNewState(steps[index]);
        }
    });

    $("#previous").click(function() {
        if (index > 0) {
            index--;
            drawNewState(steps[index]);
        }
    });
    $("#close_pop_up").click(function() {
        $("#pop_up_container").css("display", "none");

    });
    connect_handler = () => {
        socket = io("ws://" + $("#hostname")[0].value + ":" + $("#port")[0].value + "", {
            reconnection: false,
        });

        socket.on("connect_error", (err) => {
            $("#connect").addClass("connection_error");

        });

        socket.on("connect", () => {
            $("#connect").removeClass("connection_error");
            socket.emit("identify", JSON.stringify({
                "identifier": "__GUI__" + Date.now()
            }));
            $("#status")[0].innerHTML = 'Connected';
            $("#status")[0].style = 'color:green';
            $("#connect").unbind();
            $('#loadJsonButton').addClass('disabled');
            
        });

        socket.on("play", (...args) => {
            json = JSON.parse(args[0]);
            if (!json.rep) json = JSON.parse(json);
            if (json.rep && json.rep.env) {
                nextPlayer = json.active_player.name;
                const players_info = convertToPlayerInfo(json.players, json.scores);
                steps.push({"env": json.rep.env, "players":players_info, "active_player": nextPlayer});
                index = steps.length - 1;
                drawNewState(steps[index]);
            }
        });

        socket.on("ActionNotPermitted", (...args) => {
            // TODO: Display message to user
            $("#error").css("opacity", "1");
            setTimeout(function() {
                $("#error").css("opacity", "0");
            }, 2000);
            selectedPiece = null;
        })

        socket.on("disconnect", (...args) => {
            // set display block to img of id #img
            $("#status")[0].innerHTML = 'Disconnected';
            $("#status")[0].style = 'color:red';
            $("#connect").click(connect_handler);
            $('#loadJsonButton').removeClass('disabled');
        });

        socket.on("done", (...args) => {
            score = JSON.parse(args[0])
            winner_id = score["winners_id"][0]
            winner_name = ""
            winner_color = ""
            for (p in steps[steps.length - 1].players) {
                if (steps[steps.length - 1].players[p].id == winner_id) {
                    winner_name = steps[steps.length - 1].players[p].name
                    winner_color = p
                }
            }
            const nstep = score["custom_stats"][0].value;
            text = "Le joueur " + winner_name + " (<span class=\"winner_indicator " + winner_color + "\"></span>) est vainqueur apres "+ nstep + " coups !"
            $("#pop_up_container").css("display", "flex");
            $("#pop_up_text").html(text);

        })

    }

    $("#connect").click(connect_handler);
    connect_handler();

    function drawNewState(newState) {
        if (newState === undefined){
            newState = {"env": {}, "players": firstPlayersData, "active_player": "Player 1"};
        }
        active_player = newState.active_player;
        drawGrid(newState.env);
        updatePlayerDisplay(newState.players, active_player);
    }

    function convertToPlayerInfo(players, scores){
        let playerInfo = {};
        for (let player of players) {
            let playerColor = player.piece_type;
            playerInfo[playerColor] = {
                "name": player.name,
                "score": scores[player.id],
                "id": player.id,
            }
            playersName[playerColor] = player.name;
        }
        return playerInfo;
    }
    
    function drawGrid(rep_env) {
        ctxBoard.clearRect(0, 0, canvasBoard.width, canvasBoard.height);
        ctxBoard.drawImage(boardImg, 0, 0, canvasBoard.width, canvasBoard.height);

        //keys of event are (6,6) : {piece_type: 'R', owner_id: 1}
        for (const key in rep_env) {
            const [row, col] = key.split("(")[1].split(")")[0].split(",").map(Number);
            let pieceInfos = rep_env[key].piece_type;
            let pieceImg;
            pieceImg = pieceImages[pieceInfos];
            placePiece(row, col, pieceImg);
        }
    }

    

    function placePiece(row, col, pieceImg) {
        if (!pieceImg.complete || pieceImg.naturalWidth === 0) {
            pieceImg.onload = function() {
                drawPiece(getCellCoordinates(row, col), ctxBoard, pieceImg);
            };
        } else {
            drawPiece(getCellCoordinates(row, col),ctxBoard, pieceImg);
        }
    }
    
    function drawPiece(coord, ctx, pieceImg, rotate = false) {
        ctx.drawImage(pieceImg, coord.x - cellWidth, coord.y - cellSize, 2*cellWidth, 2*cellSize);
    }

    function getCellCoordinates(row, col) {
        const x = initialX + row * offsetX/2.0 + col * offsetX;
        const y = initialY + row * offsetY;
        return { x: x, y: y };
    }

    function drawPoint(x, y) {
        ctxBoard.beginPath();
        ctxBoard.arc(x, y, 3, 0, 2 * Math.PI);
        ctxBoard.fillStyle = 'red';
        ctxBoard.fill();
        ctxBoard.closePath();
    }

    function updatePlayerDisplay(players, currentPlayer) {
        // Récupérer les informations des joueurs
        const player1Info = document.getElementById('player1Info');
        const player1Name = player1Info.querySelector('.player-name');
        const player1Piece = player1Info.querySelector('.player-piece');
        
        const player2Info = document.getElementById('player2Info');
        const player2Name = player2Info.querySelector('.player-name');
        const player2Piece = player2Info.querySelector('.player-piece');
        
        // Déterminer si un swap a eu lieu en comparant les noms et les couleurs
        let swapDetected = false;
        let player1Data = null;
        let player2Data = null;
        
        // Initialiser les noms des joueurs fixes s'ils n'existent pas encore
        if (!window.initialPlayerNames) {
            window.initialPlayerNames = {};
            if (players && players['R']) {
                window.initialPlayerNames.player1 = players['R'].name;
            }
            if (players && players['B']) {
                window.initialPlayerNames.player2 = players['B'].name;
            }
        }
        
        if (players && players['R'] && players['B']) {
            // Détecter le swap : si le joueur qui était initialement rouge est maintenant bleu
            if (window.initialPlayerNames.player1 && 
                window.initialPlayerNames.player2 && 
                players['B'].name === window.initialPlayerNames.player1 && 
                players['R'].name === window.initialPlayerNames.player2) {
                swapDetected = true;
            }
            
            if (swapDetected) {
                // Après swap : garder les noms dans leurs positions mais inverser les couleurs
                player1Data = { name: window.initialPlayerNames.player1, color: 'B' };
                player2Data = { name: window.initialPlayerNames.player2, color: 'R' };
            } else {
                // Avant swap : configuration normale
                player1Data = { name: players['R'].name, color: 'R' };
                player2Data = { name: players['B'].name, color: 'B' };
            }
            
            // Mettre à jour l'affichage du joueur 1
            player1Name.textContent = player1Data.name;
            player1Piece.className = `player-piece ${player1Data.color}`;
            
            // Mettre à jour l'affichage du joueur 2
            player2Name.textContent = player2Data.name;
            player2Piece.className = `player-piece ${player2Data.color}`;
            
            // Gérer la classe active selon le joueur actuel
            if (currentPlayer === player1Data.name) {
                player1Info.classList.add('active');
                player2Info.classList.remove('active');
            } else if (currentPlayer === player2Data.name) {
                player2Info.classList.add('active');
                player1Info.classList.remove('active');
            } else {
                player1Info.classList.remove('active');
                player2Info.classList.remove('active');
            }
        }
    }

});