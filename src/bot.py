from dotenv import load_dotenv
from os import getenv
import database
import disnake
from disnake.ext import commands, tasks
import time
from conditions import *
import mercari
import token_gen


# Load system variables
load_dotenv()
TOKEN = getenv('DISCORD_TOKEN')
GUILDS = getenv('GUILDS')
USER = getenv('USERNAME')
DATABASE = getenv('DATABASE')
PASSWORD = getenv('PASSWORD')
HOST = getenv('HOST')
PORT = getenv('PORT')

# Get database cursor
connection = database.connect_to_database(USER, DATABASE, PASSWORD, HOST, PORT)
cursor = connection.cursor()

bot = commands.InteractionBot(test_guilds=[GUILDS])

@bot.event
async def on_ready():
    print(f"[-] {bot.user.name} has connected to Discord!")

@bot.event
async def on_message(ctx):
    messages = await ctx.channel.history(limit=5).flatten()

    # this means they are a new user, add to db
    if len(messages) == 1:
        database.add_new_user(connection, cursor)
    await bot.process_commands(ctx)

# Add new listing to database
@bot.slash_command()
async def add(ctx, *, search):
    # checking lengths of input strings
    total = 0
    for word in search:
        total += len(word)

    if total >= 256:
        await ctx.send("**Error:** Search term should be under 256 characters")
        return

    if len(search) == 0:
        await ctx.send("Incorrect usage of command, make sure it is formatted like this: " +
                "`!add (search term)`")
        return
    
    mercari_search = " ".join(search)

    current_time = int(time.time())

    result = database.add_to_database(connection, cursor, ctx.channel.id, mercari_search, current_time)

    if result == True:
        await ctx.send("Now tracking all new posts with the keyword **{}**.".format(mercari_search))
        await set_status()
    elif result == False:
        await ctx.send("You have already set that keyword. Check your keywords with **!list**.")

@bot.slash_command()
async def delete(ctx, *, search):
    # checking if command was input correctly
    if len(search) == 0:
        await ctx.send("Incorrect usage of command, make sure it is formatted like this: " +
                "`!delete (search term)`")
        return

    mercari_search = " ".join(search)
    channel_id = ctx.channel.id

    result = database.remove_from_database(connection, cursor, channel_id, mercari_search)
    if result == True:
        await ctx.send("No longer tracking posts with the keyword **{}**.".format(mercari_search))
        await set_status()
    elif result == False:
        await ctx.send("The keyword **{}** does not exist in the database.".format(mercari_search))

@bot.slash_command()
async def deleteall(ctx):
    channel_id = ctx.channel.id
    result = database.delete_all_user_entries(connection, cursor, channel_id)
    if result == True:
        await ctx.send("All entries have been deleted.")
        await set_status()
    elif result == False:
        await ctx.send("An error occured while while deleting your entries. Please try again.")

@bot.slash_command()
async def list(ctx):
    entries = database.get_user_entries(connection, cursor, ctx.channel.id)
    num_entries = len(entries)
    message = "**You currently have {} search terms:**\n".format(str(num_entries))
    for search, found in entries:
        message += "{} - {} listings found.\n".format(search, found)

    await ctx.send(message)

def create_embed(listing):
    url = "https://jp.mercari.com/item/" + listing['id']
    title = listing['name']
    price = "¥" + listing['price']
    thumbnail = listing['thumbnails'][0]
    condition = conditions_map[listing['itemConditionId']]
    embed=disnake.Embed(title=title, url=url, color=0xda5e22)
    embed.add_field(name="Price", value=price, inline=False)
    embed.add_field(name="Condition", value=condition, inline=False)
    embed.set_image(url=thumbnail)
    return embed

@tasks.loop(seconds=30.0)
async def search_loop():
    global connection
    global cursor
    global token
    # check for database connection
    result = database.verify_db_connection(connection, cursor)

    # if not connected, reconnect before continuing loop
    if (result == -1):
        connection = database.connect_to_database(USER, DATABASE, PASSWORD, HOST, PORT)
        cursor = connection.cursor() # get database cursor

    entries = database.get_all_entries(connection, cursor)
    # get a list containing all of the found listings
    for entry in entries:
        channel_id = entry[1]
        keyword = entry[2]
        time = entry[3]

        # get listings matching keyword from mercari
        listings = await mercari.get_item_list(keyword, token)
        if listings == False:
            token = token_gen.get_token()
            print("getting a new token")
            continue

        max_time = 0
        try:
            for l in listings['items']:
                post_created = int(l['created'])
                if post_created > time:
                    max_time = max(max_time, post_created)
                    channel = await bot.get_channel(channel_id)
                    embed = create_embed(l)
                    await channel.send("New search result for keyword **{}**.".format(keyword), embed=embed)
        except Exception as e:
            print(e)
            print(listings)
        
        if max_time > time:
            database.update_entry(connection, cursor, channel_id, keyword, max_time)

@search_loop.before_loop
async def before_search():
    await bot.wait_until_ready()

async def set_status():
    num_users = database.get_number_of_unique_users(connection, cursor)[0][0]
    num_entries = database.get_number_of_entries(connection, cursor)[0][0]
    await bot.change_presence(activity=disnake.Activity(type=disnake.ActivityType.watching, name="{} terms for {} channels".format(num_entries, num_users)))

def escape_chars(string):
    new_string = string
    chars = ['*','_','|','`','~','>','\\']
    for ch in chars:
        if ch in new_string:
            # replacing ch with escaped version of ch (ex. '*' -> '\*')
            new_string = new_string.replace(ch, "\\" + ch)
    return new_string

if __name__ == "__main__":
    if database.database_setup(connection, cursor):
        token = token_gen.get_token()
        # starting scraper in seperate coroutine
        search_loop.start()
        # get_new_token.start()
        # starting bot on main thread
        bot.run(TOKEN)
