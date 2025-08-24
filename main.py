import discord
from discord.ext import commands, tasks
import asyncio
import json
from datetime import datetime, timezone, timedelta
import os
import re
from typing import Dict, List, Optional
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import time
import pytz
import random

# Bot configuration
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID', '0'))
LEADERBOARD_CHANNEL = int(os.getenv('LEADERBOARD_CHANNEL', '0'))
PORT = int(os.getenv('PORT', 8080))
RENDER_APP_URL = os.getenv('RENDER_APP_URL')  # Set this to your app's URL like https://your-app.onrender.com

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        # Create a simple status page
        status_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Trackmania Weekly Shorts Bot</title>
            <meta http-equiv="refresh" content="30">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background: #2c2f33; color: white; }}
                .container {{ max-width: 600px; margin: 0 auto; }}
                .status {{ background: #23272a; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .online {{ color: #43b581; }}
                .info {{ color: #7289da; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🏁 Trackmania Weekly Shorts Bot</h1>
                <div class="status">
                    <h2 class="online">✅ Bot Status: Online</h2>
                    <p class="info">Current Week: {bot.competition.current_week if 'bot' in globals() and bot.competition else 'Loading...'}</p>
                    <p class="info">Registered Players: {len(bot.competition.player_names) if 'bot' in globals() and bot.competition else 'Loading...'}</p>
                    <p>Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
                </div>
                <div class="status">
                    <h3>Available Commands:</h3>
                    <ul>
                        <li><code>!tm register &lt;username&gt;</code> - Register for competition</li>
                        <li><code>!tm time &lt;map&gt; &lt;time&gt;</code> - Submit a time</li>
                        <li><code>!tm leaderboard</code> - View overall leaderboard</li>
                        <li><code>!tm map &lt;number&gt;</code> - View map-specific leaderboard</li>
                    </ul>
                </div>
            </div>
        </body>
        </html>
        """
        self.wfile.write(status_html.encode())
    
    def log_message(self, format, *args):
        # Suppress HTTP server logs to keep console clean
        pass

def start_http_server():
    """Start HTTP server for Render web service health checks"""
    try:
        server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
        print(f"🌐 HTTP server started on port {PORT}")
        server.serve_forever()
    except Exception as e:
        print(f"❌ HTTP server error: {e}")

class WeeklyCompetition:
    def __init__(self):
        self.data_file = "competition_data.json"
        self.current_week = self.get_current_week()
        self.player_times = {}
        self.player_names = {}
        self.author_times = {}
        self.week_maps = {
            1: "Map 1 - Short Track Alpha",
            2: "Map 2 - Short Track Beta", 
            3: "Map 3 - Short Track Gamma",
            4: "Map 4 - Short Track Delta",
            5: "Map 5 - Short Track Epsilon"
        }
        self.load_data()

    def load_data(self):
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                
                self.player_names = {int(k): v for k, v in data.get('player_names', {}).items()}
                
                saved_week = data.get('current_week', '')
                if saved_week == self.current_week:
                    self.player_times = {int(k): {int(map_k): map_v for map_k, map_v in v.items()} 
                                       for k, v in data.get('player_times', {}).items()}
                    self.author_times = {int(k): v for k, v in data.get('author_times', {}).items()}
                    print(f"📊 Loaded existing data for week {self.current_week}")
                else:
                    self.player_times = {}
                    self.author_times = {}
                    print(f"🆕 New week detected! Reset times, kept {len(self.player_names)} registered players")
                    self.save_data()
            else:
                print("📝 No existing data file found, starting fresh")
        except Exception as e:
            print(f"⚠️ Error loading data: {e}")

    def save_data(self):
        try:
            data = {
                'current_week': self.current_week,
                'player_names': self.player_names,
                'player_times': self.player_times,
                'author_times': self.author_times,
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=2)
            
        except Exception as e:
            print(f"⚠️ Error saving data: {e}")

    def get_current_week(self) -> str:
        """Get current week based on Sunday 6:15 PM CET reset time"""
        cet = pytz.timezone('Europe/Berlin')  # CET/CEST timezone
        now_cet = datetime.now(cet)
        
        # Calculate days since last Sunday
        weekday = now_cet.weekday()  # Monday=0, Sunday=6
        days_since_sunday = (weekday + 1) % 7  # Convert so Sunday=0
        
        # Find the most recent Sunday 6:15 PM
        if days_since_sunday == 0:  # It's Sunday
            if now_cet.time() < datetime.strptime("18:15", "%H:%M").time():
                # Before 6:15 PM on Sunday, use previous Sunday
                days_back = 7
            else:
                # After 6:15 PM on Sunday, use today
                days_back = 0
        else:
            days_back = days_since_sunday
        
        week_start = now_cet - timedelta(days=days_back)
        week_start = week_start.replace(hour=18, minute=15, second=0, microsecond=0)
        
        # Format as YYYY-MM-DD for the Sunday that started this week
        return week_start.strftime("%Y-%m-%d")

    def register_player(self, discord_id: int, tm_username: str):
        self.player_names[discord_id] = tm_username
        if discord_id not in self.player_times:
            self.player_times[discord_id] = {}
        self.save_data()

    def add_time(self, discord_id: int, map_num: int, time_ms: int) -> bool:
        if discord_id not in self.player_names:
            return False
        if map_num not in range(1, 6):
            return False
        if discord_id not in self.player_times:
            self.player_times[discord_id] = {}
        self.player_times[discord_id][map_num] = time_ms
        self.save_data()
        return True

    def set_author_time(self, map_num: int, time_ms: int) -> bool:
        if map_num not in range(1, 6):
            return False
        self.author_times[map_num] = time_ms
        self.save_data()
        return True

    def get_map_leaderboard(self, map_num: int) -> List[Dict]:
        if map_num not in range(1, 6):
            return []

        players = []
        for discord_id in self.player_times:
            if map_num in self.player_times[discord_id]:
                time = self.player_times[discord_id][map_num]
                players.append({
                    'discord_id': discord_id,
                    'tm_username': self.player_names.get(discord_id, 'Unknown'),
                    'time': time
                })

        sorted_players = sorted(players, key=lambda x: x['time'])
        
        if sorted_players:
            first_time = sorted_players[0]['time']
            for player in sorted_players:
                if player['time'] == first_time:
                    player['split'] = None
                else:
                    player['split'] = player['time'] - first_time

        return sorted_players

    def get_overall_leaderboard(self) -> List[Dict]:
        players = []

        for discord_id in self.player_times:
            times = self.player_times[discord_id]
            if not times:
                continue

            author_medals = 0
            for map_num, time_ms in times.items():
                if map_num in self.author_times:
                    if time_ms <= self.author_times[map_num]:
                        author_medals += 1

            players.append({
                'discord_id': discord_id,
                'tm_username': self.player_names.get(discord_id, 'Unknown'),
                'maps_completed': len(times),
                'individual_times': times,
                'author_medals': author_medals
            })

        return sorted(players, key=lambda x: (-x['maps_completed'], -x['author_medals'], x['tm_username'].lower()))

    def get_overall_totals_leaderboard(self) -> List[Dict]:
        """Get leaderboard based on total time across all completed maps"""
        players = []

        for discord_id in self.player_times:
            times = self.player_times[discord_id]
            if not times:
                continue

            # Calculate total time (only include players who have completed all 5 maps)
            if len(times) == 5:
                total_time = sum(times.values())
                players.append({
                    'discord_id': discord_id,
                    'tm_username': self.player_names.get(discord_id, 'Unknown'),
                    'total_time': total_time,
                    'individual_times': times
                })

        # Sort by total time
        sorted_players = sorted(players, key=lambda x: x['total_time'])
        
        # Calculate splits from first place
        if sorted_players:
            first_time = sorted_players[0]['total_time']
            for player in sorted_players:
                if player['total_time'] == first_time:
                    player['split'] = None
                else:
                    player['split'] = player['total_time'] - first_time

        return sorted_players

    def reset_week(self):
        old_week = self.current_week
        self.current_week = self.get_current_week()
        self.player_times = {}
        self.author_times = {}
        self.save_data()
        print(f"🔄 Week reset from {old_week} to {self.current_week}")

class WeeklyShortsBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!tm ', intents=intents)
        self.competition = WeeklyCompetition()
        # Remove the default help command so we can create our own
        self.remove_command('help')

    async def setup_hook(self):
        self.weekly_reset_check.start()
        self.keep_alive.start()  # Start keep-alive task
        print("🏁 Trackmania Weekly Shorts Bot is ready!")
        print(f"📅 Current competition week: {self.competition.current_week}")

    @tasks.loop(minutes=14)  # Ping every 14 minutes to prevent sleep
    async def keep_alive(self):
        """Keep the Render service awake by pinging itself"""
        if RENDER_APP_URL:
            try:
                print(f"🏓 Attempting keep-alive ping to {RENDER_APP_URL}")
                response = requests.get(RENDER_APP_URL, timeout=30)
                print(f"🏓 Keep-alive ping: {response.status_code}")
            except Exception as e:
                print(f"⚠️ Keep-alive ping failed: {e}")
        else:
            print("⚠️ Keep-alive ping skipped - RENDER_APP_URL not set")

    @tasks.loop(minutes=5)  # Check every 5 minutes around reset time
    async def weekly_reset_check(self):
        current_week = self.competition.get_current_week()
        if current_week != self.competition.current_week:
            await self.handle_week_reset(current_week)

    async def handle_week_reset(self, new_week: str):
        channel = self.get_channel(LEADERBOARD_CHANNEL)
        if channel:
            old_week = self.competition.current_week
            self.competition.reset_week()
            
            # Convert week date back to readable format
            try:
                week_date = datetime.strptime(new_week, "%Y-%m-%d")
                week_display = week_date.strftime("Week of %B %d, %Y")
            except:
                week_display = new_week
            
            embed = discord.Embed(
                title=f"🆕 New Week Started - {week_display}",
                description="Time for new Weekly Shorts! The maps have reset in-game. Register and submit your times for the new maps!",
                color=discord.Color.blue()
            )
            embed.add_field(name="🕕", value="Reset at Sunday 6:15 PM CET", inline=True)
            await channel.send(embed=embed)

# Initialize bot
bot = WeeklyShortsBot()

@bot.event
async def on_ready():
    print(f'🤖 Bot logged in as {bot.user}!')
    print(f"📊 Loaded {len(bot.competition.player_names)} registered players")

@bot.command(name='register')
async def register_player(ctx, *, trackmania_username: str):
    if len(trackmania_username) > 50:
        await ctx.send("❌ Username too long! Please use a shorter name.")
        return
    bot.competition.register_player(ctx.author.id, trackmania_username)
    await ctx.send(f"✅ Registered `{trackmania_username}` for {ctx.author.mention}!")

@bot.command(name='time', aliases=['submit', 't'])
async def submit_time(ctx, map_num: int, *, time_str: str):
    if ctx.author.id not in bot.competition.player_names:
        await ctx.send("❌ Please register first with `!tm register <your_trackmania_username>`")
        return

    if map_num not in range(1, 6):
        await ctx.send("❌ Map number must be between 1 and 5!")
        return

    time_ms = parse_time(time_str)
    if time_ms is None:
        await ctx.send("❌ Invalid time format! Use formats like: `1:23.456`, `83.456`, or `83456` (ms)")
        return

    if not (1000 <= time_ms <= 600000):
        await ctx.send("❌ Time seems unreasonable (must be between 1 second and 10 minutes)")
        return

    success = bot.competition.add_time(ctx.author.id, map_num, time_ms)
    if success:
        formatted_time = format_time(time_ms)
        tm_username = bot.competition.player_names[ctx.author.id]

        embed = discord.Embed(title="⏱️ Time Submitted!", color=discord.Color.green())
        embed.add_field(name="Player", value=tm_username, inline=True)
        embed.add_field(name="Map", value=f"#{map_num}", inline=True)
        embed.add_field(name="Time", value=formatted_time, inline=True)

        # Check for author medal
        if map_num in bot.competition.author_times:
            author_time = bot.competition.author_times[map_num]
            if time_ms <= author_time:
                embed.add_field(name="🏆", value="Author Medal! :authormedal:", inline=True)

        # Check if they're dominating (1+ second ahead of 2nd place)
        map_leaderboard = bot.competition.get_map_leaderboard(map_num)
        if len(map_leaderboard) >= 2:
            first_place = map_leaderboard[0]
            second_place = map_leaderboard[1]
            if (first_place['discord_id'] == ctx.author.id and 
                second_place['time'] - first_place['time'] >= 1000):  # 1000ms = 1 second
                embed.add_field(name="🏎️", value="Woah! Slow down speed racer!", inline=True)

        # Easter egg for times ending in 69
        if str(time_ms).endswith('69'):
            embed.add_field(name="😏", value="*nice ;)*", inline=True)

        await ctx.send(embed=embed)

@bot.command(name='setauthor', aliases=['author'])
@commands.has_permissions(administrator=True)
async def set_author_time(ctx, map_num: int, *, time_str: str):
    """Set author time for a map - only admins can use this"""
    if map_num not in range(1, 6):
        await ctx.send("❌ Map number must be between 1 and 5!")
        return

    time_ms = parse_time(time_str)
    if time_ms is None:
        await ctx.send("❌ Invalid time format! Use formats like: `1:23.456`, `83.456`, or `83456` (ms)")
        return

    if not (1000 <= time_ms <= 600000):
        await ctx.send("❌ Time seems unreasonable (must be between 1 second and 10 minutes)")
        return

    success = bot.competition.set_author_time(map_num, time_ms)
    if success:
        formatted_time = format_time(time_ms)
        embed = discord.Embed(title="🏆 Author Time Set!", color=discord.Color.gold())
        embed.add_field(name="Map", value=f"#{map_num}", inline=True)
        embed.add_field(name="Author Time", value=f"{formatted_time} :authormedal:", inline=True)
        embed.add_field(name="Challenge", value="Beat this time to earn an Author Medal!", inline=False)
        
        # Easter egg for author times ending in 69
        if str(time_ms).endswith('69'):
            embed.add_field(name="😏", value="*nice ;)*", inline=True)
            
        await ctx.send(embed=embed)

@bot.command(name='compare', aliases=['vs'])
async def compare_players(ctx, member1: discord.Member = None, member2: discord.Member = None):
    """Compare two players' times"""
    if not member1:
        member1 = ctx.author
    if not member2:
        await ctx.send("❌ Please mention a player to compare with! Example: `!tm compare @player`")
        return
    
    if member1.id not in bot.competition.player_names or member2.id not in bot.competition.player_names:
        await ctx.send("❌ Both players must be registered to compare!")
        return
    
    name1 = bot.competition.player_names[member1.id]
    name2 = bot.competition.player_names[member2.id]
    times1 = bot.competition.player_times.get(member1.id, {})
    times2 = bot.competition.player_times.get(member2.id, {})
    
    embed = discord.Embed(
        title=f"⚔️ {name1} vs {name2}",
        description="Head-to-head comparison",
        color=discord.Color.orange()
    )
    
    wins1 = wins2 = ties = 0
    comparison_text = ""
    
    for map_num in range(1, 6):
        if map_num in times1 and map_num in times2:
            time1 = times1[map_num]
            time2 = times2[map_num]
            
            if time1 < time2:
                winner = f"🟢 {name1}"
                wins1 += 1
                diff = format_time(time2 - time1)
            elif time2 < time1:
                winner = f"🟢 {name2}"
                wins2 += 1
                diff = format_time(time1 - time2)
            else:
                winner = "🟡 TIE"
                ties += 1
                diff = "0.000"
            
            comparison_text += f"**Map {map_num}:** {winner} (±{diff})\n"
        elif map_num in times1:
            comparison_text += f"**Map {map_num}:** 🟢 {name1} (no time from {name2})\n"
            wins1 += 1
        elif map_num in times2:
            comparison_text += f"**Map {map_num}:** 🟢 {name2} (no time from {name1})\n"
            wins2 += 1
        else:
            comparison_text += f"**Map {map_num}:** ⚪ Neither submitted\n"
    
    embed.add_field(name="📊 Results", value=comparison_text, inline=False)
    embed.add_field(name=f"🏆 {name1}", value=f"{wins1} wins", inline=True)
    embed.add_field(name=f"🏆 {name2}", value=f"{wins2} wins", inline=True)
    embed.add_field(name="🤝 Ties", value=f"{ties}", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='motivate', aliases=['motivation', 'hype'])
async def motivate_player(ctx):
    """Get some racing motivation!"""
    motivations = [
        "🏋️ Jose, put down the dumbbells and pick up the controller - those muscles won't help you brake later!",
        "🍕 Jose, that ugly food isn't going to fuel your racing... but somehow you'll still dominate!",
        "🚴 Grace, you've already survived one crash this week - what's a few virtual walls gonna do?",
        "🚴 Alex, at least in Trackmania when you crash you just respawn instead of needing bandages!",
        "🚬 Myka, smoking breaks are for AFTER you beat the author time - priorities!",
        "🎵 Myka, channel that musical rhythm into perfect racing lines!",
        "🍷 Jurbi, save the wine for celebrating your victory lap!",
        "🚌 Jurbi, the bus may be slow but your racing doesn't have to be!",
        "📺 Alistair, those old TV shows taught you patience - now use it to nail that perfect run!",
        "🎮 Alistair, I know you hate playing with friends, but you love beating them at racing!",
        "💪 Margo, use that strength to grip the controller while you demolish the competition!",
        "📏 Margo, being tall gives you a better view of the track - use that advantage!",
        "😍 Margo, you're handsome AND fast? Save some talent for the rest of OTAW!",
        "📅 OTAW crew, it's One Thing A Week and this week's thing is SPEED!",
        "🏁 Time to show everyone what One Thing A Week mastery looks like on the track!"
    ]
    
    motivation = random.choice(motivations)
    
    embed = discord.Embed(
        title="💪 OTAW Racing Motivation",
        description=motivation,
        color=discord.Color.red()
    )
    
    await ctx.send(embed=embed)

@bot.command(name='authortimes', aliases=['authors', 'at'])
async def show_author_times(ctx):
    """Show all set author times"""
    if not bot.competition.author_times:
        await ctx.send("❌ No author times have been set yet!")
        return
    
    embed = discord.Embed(
        title="🏆 Author Times",
        description="Beat these times to earn Author Medals :authormedal:",
        color=discord.Color.gold()
    )
    
    for map_num in range(1, 6):
        if map_num in bot.competition.author_times:
            time_ms = bot.competition.author_times[map_num]
            formatted_time = format_time(time_ms)
            embed.add_field(
                name=f"Map {map_num}",
                value=f"{formatted_time} :authormedal:",
                inline=True
            )
        else:
            embed.add_field(
                name=f"Map {map_num}",
                value="Not set",
                inline=True
            )
    
    await ctx.send(embed=embed)

@bot.command(name='bothelp', aliases=['commands', 'h'])
async def show_help(ctx):
    """Show all available commands with examples"""
    embed = discord.Embed(
        title="🏁 Trackmania Weekly Shorts Bot Commands",
        description="Your guide to competitive weekly racing! 🏎️",
        color=discord.Color.blue()
    )
    
    # Player Commands
    embed.add_field(
        name="👤 **Player Commands**",
        value=(
            "`!tm register <username>` - Register for weekly competition\n"
            "`!tm time <map> <time>` - Submit your time (e.g. `!tm time 1 1:23.456`)\n"
            "`!tm leaderboard` - View weekly leaderboard with all maps\n"
            "`!tm map <number>` - View specific map leaderboard (1-5)\n"
            "`!tm compare @player` - Compare your times with another player\n"
            "`!tm motivate` - Get some racing motivation!"
        ),
        inline=False
    )
    
    # Information Commands
    embed.add_field(
        name="📊 **Information Commands**",
        value=(
            "`!tm authortimes` - View all author medal times\n"
            "`!tm bothelp` - Show this help message"
        ),
        inline=False
    )
    
    # Admin Commands
    embed.add_field(
        name="🛠️ **Admin Commands**",
        value=(
            "`!tm setauthor <map> <time>` - Set author time for a map\n"
            "*Only administrators can use these commands*"
        ),
        inline=False
    )
    
    # Time Format Examples
    embed.add_field(
        name="⏱️ **Time Format Examples**",
        value=(
            "`1:23.456` - 1 minute, 23.456 seconds\n"
            "`83.456` - 83.456 seconds\n"
            "`83456` - 83,456 milliseconds"
        ),
        inline=False
    )
    
    # Footer with current week info
    try:
        week_date = datetime.strptime(bot.competition.current_week, "%Y-%m-%d")
        week_display = week_date.strftime("Week of %B %d, %Y")
        embed.set_footer(text=f"Current Competition: {week_display} • Next Reset: Sunday 6:15 PM CET")
    except:
        embed.set_footer(text=f"Current Week: {bot.competition.current_week} • Next Reset: Sunday 6:15 PM CET")
    
    await ctx.send(embed=embed)

@bot.command(name='leaderboard', aliases=['lb'])
async def show_leaderboard(ctx):
    # Check if anyone has submitted times
    has_times = any(bot.competition.player_times.values())
    if not has_times:
        await ctx.send("📊 No times submitted yet this week!")
        return

    description = f"**Week {bot.competition.current_week} Leaderboard**\n\n"
    
    # Get medal emojis
    medals = ["🥇", "🥈", "🥉"]
    
    # Process each map
    for map_num in range(1, 6):
        map_leaderboard = bot.competition.get_map_leaderboard(map_num)
        
        description += f"**Map {map_num}**\n"
        
        if not map_leaderboard:
            description += "No times submitted\n\n"
            continue
            
        for i, player in enumerate(map_leaderboard):  # Show all players
            if i < 3:
                medal = medals[i]
            else:
                medal = f"#{i+1}"
            
            time_str = format_time(player['time'])
            
            if player['split'] is None:
                split_text = ""
            else:
                split_str = format_time(player['split'])
                split_text = f"  (+{split_str})"
            
            # Add author medal emoji if they beat author time
            author_medal = ""
            if map_num in bot.competition.author_times:
                if player['time'] <= bot.competition.author_times[map_num]:
                    author_medal = " :authormedal:"
            
            description += f"{medal} {player['tm_username']} — {time_str}{split_text}{author_medal}\n"
        
        description += "\n"
    
    # Add overall totals section
    overall_totals = bot.competition.get_overall_totals_leaderboard()
    if overall_totals:
        description += "**Overall Totals**\n"
        for i, player in enumerate(overall_totals):  # Show all players who completed all maps
            if i < 3:
                medal = medals[i]
            else:
                medal = f"#{i+1}"
            
            time_str = format_time(player['total_time'])
            
            if player['split'] is None:
                split_text = ""
            else:
                split_str = format_time(player['split'])
                split_text = f"  (+{split_str})"
            
            description += f"{medal} {player['tm_username']} — {time_str}{split_text}\n"
    else:
        description += "**Overall Totals**\nNo players have completed all 5 maps yet"

    # Create embed
    embed = discord.Embed(
        title="🏁 Weekly Shorts Leaderboard",
        description=description,
        color=discord.Color.green()
    )
    
    # Add footer showing current week
    try:
        week_date = datetime.strptime(bot.competition.current_week, "%Y-%m-%d")
        week_display = week_date.strftime("Week of %B %d, %Y")
        embed.set_footer(text=f"{week_display} • Resets Sunday 6:15 PM CET")
    except:
        embed.set_footer(text=f"{bot.competition.current_week} • Resets Sunday 6:15 PM CET")

    await ctx.send(embed=embed)

@bot.command(name='map')
async def show_map_leaderboard(ctx, map_num: int):
    if map_num not in range(1, 6):
        await ctx.send("❌ Map number must be between 1 and 5!")
        return

    map_leaderboard = bot.competition.get_map_leaderboard(map_num)
    if not map_leaderboard:
        await ctx.send(f"📊 No times submitted for Map {map_num} yet!")
        return

    embed = discord.Embed(
        title=f"🗺️ Map {map_num} Leaderboard",
        description=bot.competition.week_maps[map_num],
        color=discord.Color.orange()
    )

    if map_num in bot.competition.author_times:
        author_time = format_time(bot.competition.author_times[map_num])
        embed.add_field(name="🏅 Author Medal", value=f"⏱️ {author_time}", inline=False)

    for i, player in enumerate(map_leaderboard[:10], 1):
        time_str = format_time(player['time'])
        
        if player['split'] is None:
            display_text = f"⏱️ {time_str}"
        else:
            split_str = format_time(player['split'])
            display_text = f"⏱️ {time_str} (+{split_str})"
        
        if map_num in bot.competition.author_times:
            if player['time'] <= bot.competition.author_times[map_num]:
                display_text += " :authormedal:"

        embed.add_field(
            name=f"#{i} - {player['tm_username']}",
            value=display_text,
            inline=False
        )

    await ctx.send(embed=embed)


def parse_time(time_str: str) -> Optional[int]:
    time_str = time_str.strip().replace(',', '.')

    # Match format: M:SS.mmm or M:SS:mmm (minutes:seconds.milliseconds)
    match = re.match(r'^(\d+):(\d{1,2})[:.](\d{1,3})$', time_str)
    if match:
        minutes, seconds, ms = match.groups()
        ms = ms.ljust(3, '0')[:3]  # Pad to 3 digits or truncate
        return int(minutes) * 60000 + int(seconds) * 1000 + int(ms)

    # Match format: SS.mmm (seconds.milliseconds)
    match = re.match(r'^(\d+)\.(\d{1,3})$', time_str)
    if match:
        seconds, ms = match.groups()
        ms = ms.ljust(3, '0')[:3]  # Pad to 3 digits or truncate
        return int(seconds) * 1000 + int(ms)

    # Match format: whole number (assume milliseconds)
    match = re.match(r'^(\d+)$', time_str)
    if match:
        return int(time_str)

    return None

def format_time(ms: int) -> str:
    if ms <= 0:
        return "00:00.000"

    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    milliseconds = ms % 1000

    return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

async def run_bot():
    """Run the Discord bot"""
    try:
        await bot.start(TOKEN)
    except Exception as e:
        print(f"❌ Bot error: {e}")

def main():
    if not TOKEN:
        print("❌ Please set DISCORD_BOT_TOKEN environment variable")
        print(f"Current TOKEN value: {repr(TOKEN)}")
        exit(1)

    print("🚀 Starting Trackmania Weekly Shorts Bot...")
    print(f"🌐 Will start HTTP server on port {PORT}")
    print(f"🔧 RENDER_APP_URL environment variable: {repr(RENDER_APP_URL)}")
    if RENDER_APP_URL:
        print(f"🏓 Keep-alive enabled for: {RENDER_APP_URL}")
    else:
        print("⚠️ RENDER_APP_URL not set - keep-alive disabled")
    
    # Start HTTP server in a separate thread
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    
    # Give HTTP server a moment to start
    time.sleep(2)
    
    # Run the Discord bot
    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Bot crashed: {e}")

if __name__ == "__main__":
    main()
