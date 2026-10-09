import os
import aiohttp
from aiohttp import web
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
APPLICATION_CHANNEL_ID = int(os.getenv("DISCORD_APPLICATION_CHANNEL_ID"))
ADMIN_ROLE_ID = int(os.getenv("DISCORD_ADMIN_ROLE_ID"))
WHITELIST_ROLE_ID = int(os.getenv("DISCORD_WHITELIST_ROLE_ID"))
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
BOT_API_KEY = os.getenv("BOT_API_KEY")
BACKEND_URL = os.getenv("BACKEND_URL")

member_count = 0

bot = commands.Bot(command_prefix="!",intents=discord.Intents.all())


def is_admin(interaction: discord.Interaction):
    if not interaction.guild:
        return False

    role = interaction.guild.get_role(ADMIN_ROLE_ID)
    if not role:
        return False

    return role in interaction.user.roles

async def add_whitelist_role(guild, user_id):
    if guild is None:
        raise RuntimeError("Guild not found")

    member = guild.get_member(int(user_id))
    if member is None:
        member = await guild.fetch_member(int(user_id))

    role = guild.get_role(WHITELIST_ROLE_ID)
    if role is None:
        raise RuntimeError("Whitelist role not found")

    await member.add_roles(role, reason="Whitelist application accepted")


async def get_application_history(discord_id):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BACKEND_URL}api/whitelist/history/{discord_id}",
                headers={
                    "Authorization": f"Bearer {BOT_API_KEY}"
                }
            ) as response:
                data = await response.json()
                if response.status != 200:
                    print(f"History API error:", data)
                    return None

                return data.get("applications", [])
    except Exception as error:
        print("Failed to fetch application history:", error)
        return None

async def show_application_history(interaction, discord_id):
    try:
        applications = await get_application_history(discord_id)

        if applications is None:
            await interaction.response.send_message(
                "Hakemushistorian hakeminen epäonnistui.",
                ephemeral=True
            )
            return

        if not applications:
            await interaction.response.send_message(
                "Tällä käyttäjällä ei ole aikaisempia whitelist-hakemuksia.",
                ephemeral=True
            )
            return

        embeds = []

        for application in applications:
            status = application["status"]

            if status == "accepted":
                status_text = "✅ Hyväksytty"
                color = discord.Color.green()

            elif status == "denied":
                status_text = "❌ Hylätty"
                color = discord.Color.red()

            else:
                status_text = "⏳ Käsittelyssä"
                color = discord.Color.orange()

            embed = discord.Embed(
                title=f"📋 Whitelist-hakemus #{application['id']}",
                color=color
            )

            embed.add_field(
                name="Status",
                value=status_text,
                inline=True
            )

            embed.add_field(
                name="Ikä",
                value=str(application["age"]),
                inline=True
            )

            embed.add_field(
                name="📅 Lähetetty",
                value=str(application["created_at"]),
                inline=False
            )

            embed.add_field(
                name="🔄 Päivitetty",
                value=str(application["updated_at"]),
                inline=False
            )

            embed.add_field(
                name="📖 RP Kokemus",
                value=application["experience"],
                inline=False
            )

            embed.add_field(
                name="🎭 Hahmo",
                value=application["ic"],
                inline=False
            )

            embed.add_field(
                name="👤 Roolipelaaja",
                value=application["ooc"],
                inline=False
            )

            if application["admin_note"]:
                embed.add_field(
                    name="📝 Ylläpidon huomio",
                    value=application["admin_note"],
                    inline=False
                )

            embeds.append(embed)

        await interaction.response.send_message(
            embeds=embeds,
            ephemeral=True
        )

    except Exception as error:
        print("Show application history error:", error)

        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Hakemushistorian näyttäminen epäonnistui.",
                ephemeral=True
            )


class ReasonModal(discord.ui.Modal):
    def __init__(self, application_id, action, message_id, user_id):
        super().__init__(title="Hyväksymisen syy" if action == "accept" else "Hylkäämisen syy")

        self.application_id = application_id
        self.action = action
        self.message_id = message_id
        self.user_id = user_id

        self.reason = discord.ui.TextInput(
            label ="Syy",
            placeholder="Kirjoita syy tähän...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000
        )

        self.add_item(self.reason)

    async def on_submit(self, interaction : discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        admin_note = self.reason.value

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{BACKEND_URL}api/whitelist/{self.application_id}/{self.action}", headers={
                    "Authorization": f"Bearer {BOT_API_KEY}",
                    "Content-Type": "application/json"
                }, json={"adminNote":admin_note}) as response:
                    data = await response.json()
                    print(
                        f"Reason action={self.action} application_id={self.application_id} "
                        f"status={response.status}"
                    )

                    if response.status != 200:
                        if response.status == 409:
                            await interaction.followup.send(
                                "Hakemus on jo käsitelty toisella päätöksellä.",
                                ephemeral=True
                            )
                            return

                        if response.status == 404:
                            await interaction.followup.send(
                                "Hakemusta ei löydy tietokannasta. Tarkista application ID.",
                                ephemeral=True
                            )
                            return

                        await interaction.followup.send(f"Virhe: {data.get('error',
                        'Tuntematon virhe')}", ephemeral=True)
                        return

            if self.action == "accept":
                await add_whitelist_role(interaction.guild, self.user_id)

            message = await interaction.channel.fetch_message(self.message_id)
            view = WhitelistView(self.application_id, self.user_id)

            for child in view.children:
                child.disabled = True

            embed = message.embeds[0]
            embed.color = discord.Color.green() if self.action == "accept" else discord.Color.red()
            status = "✅ Hyväksytty" if self.action == "accept" else "❌ Hylätty"
            embed.add_field(name="Status", value=f"{status}\nSyy: {admin_note}", inline=False)
            await message.edit(embed=embed, view=view)
            await interaction.followup.send("Hakemus käsitelty onnistuneesti ✅", ephemeral=True)

        except Exception as error:
            print(f"Reason modal error:", error)
            await interaction.followup.send("Hakemuksen käsittely epäonnistui", ephemeral=True)

class WhitelistView(discord.ui.View):
    def __init__(self, application_id, user_id):
        super().__init__(timeout=None)
        self.application_id = application_id
        self.user_id = user_id

    @discord.ui.button(
        label = "Hyväksy",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="wl_accept"
    )
    async def accept(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_admin(interaction):
            await interaction.response.send_message("Sinulla ei ole oikeutta käsitellä whitelist-hakemuksia", ephemeral=True)
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{BACKEND_URL}api/whitelist/{self.application_id}/accept",headers={"Authorization": f"Bearer {BOT_API_KEY}"}) as response:
                    data = await response.json()

                    if response.status != 200:
                        await interaction.response.send_message(f"Virhe: {data.get('error', 'Tuntematon virhe')}", ephemeral=True)
                        return
            await add_whitelist_role(interaction.guild, self.user_id)
            for child in self.children:
                child.disabled = True
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.add_field(name="Status", value="✅ Hyväksytty", inline=False)
            await interaction.message.edit(embed=embed, view=self)
            await interaction.response.send_message(f"Hakemus #{self.application_id} hyväksytty! ✅", ephemeral=True)
        except Exception as error:
            print("Accept error:", error)
            await interaction.response.send_message("Hakemuksen hyväksyminen epäonnistui.",ephemeral=True)
        # await interaction.response.send_message(f"Hyväksytään hakemus #{self.application_id}...", ephemeral=True)

    @discord.ui.button(
        label="Hylkää",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        custom_id="wl_deny"
    )
    async def deny(
        self, interaction:discord.Interaction,button:discord.ui.Button
    ):
        if not is_admin(interaction):
            await interaction.response.send_message("Sinulla ei ole oikeutta käsitellä whitelist-hakemuksia", ephemeral=True)
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{BACKEND_URL}api/whitelist/{self.application_id}/deny",headers={"Authorization": f"Bearer {BOT_API_KEY}"}) as response:
                    data = await response.json()

                    if response.status != 200:
                        await interaction.response.send_message(f"Virhe: {data.get('error', 'Tuntematon virhe')}", ephemeral=True)
                        return
            for child in self.children:
                child.disabled = True
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.red()
            embed.add_field(name="Status", value="❌ Hylätty", inline=False)
            await interaction.message.edit(embed=embed, view=self)
            await interaction.response.send_message(f"Hakemus #{self.application_id} hylätty! ❌", ephemeral=True)
        except Exception as error:
            print("Accept error:", error)
            await interaction.response.send_message("Hakemuksen hyväksyminen epäonnistui.",ephemeral=True)
        # await interaction.response.send_message(f"Hylätään hakemus #{self.application_id}...", ephemeral=True)
    @discord.ui.button(
        label="Hyväksy syyllä",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="wl_accept_reason"
    )

    async def accept_reason(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not is_admin(interaction):
            await interaction.response.send_message("Sinulla ei ole oikeutta käsitellä whitelist-hakemuksia", ephemeral=True)
            return
        await interaction.response.send_modal(ReasonModal(self.application_id, "accept", interaction.message.id, self.user_id))


    @discord.ui.button(
        label="Hylkää syyllä",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        custom_id="wl_deny_reason"
    )

    async def deny_reason(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not is_admin(interaction):
            await interaction.response.send_message("Sinulla ei ole oikeutta käsitellä whitelist-hakemuksia", ephemeral=True)
            return
        await interaction.response.send_modal(ReasonModal(self.application_id, "deny", interaction.message.id, self.user_id))

    # @discord.ui.button(label="Avaa tiketti hakijan kanssa",style=discord.ButtonStyle.gray,emoji="❌",custom_id="wl_ticket")
    # async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
    #     if not is_admin(interaction):
    #         await interaction.response.send_message("Sinulla ei ole oikeutta avata tikettiä whitelist-hakijan kanssa.", ephemeral=True)
    #         return
    #     await interaction.response.send_message("Avasit tiketin hakijan kanssa",ephemeral=True)
    @discord.ui.button(
        label = "Hakemus historia",
        style=discord.ButtonStyle.grey,
        emoji="❓",
        custom_id="wl_history"
    )
    async def wl_history(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("Sinulla ei ole oikeutta tarkastella whitelist-hakemushistoriaa", ephemeral=True)
            return
        await show_application_history(interaction, self.user_id)

async def send_whitelist_application(data):
    channel = bot.get_channel(APPLICATION_CHANNEL_ID)
    if channel is None:
        raise RuntimeError("Whitelist channel not found")

    embed = discord.Embed(title="📝 Whitelist hakemus",description=f"Hakemus #{data['applicationId']}", color=discord.Color.blurple())


    embed.add_field(
        name="👤 Hakija",
        value=f"<@{data['discordId']}>",
        inline=True
    )

    embed.add_field(
        name="🎂 Ikä",
        value=str(data["age"]),
        inline=True
    )

    embed.add_field(
        name="📖 RP Kokemus",
        value=data["experience"],
        inline=False
    )

    embed.add_field(
        name="Hahmo",
        value=data["ic"],
        inline=False
    )

    embed.add_field(
        name="Roolipelaaja",
        value=data["ooc"],
        inline=False
    )

    embed.set_footer(
        text=f"Hakemus ID: {data['applicationId']}"
    )

    view = WhitelistView(data["applicationId"],data["discordId"])

    message = await channel.send(
        embed=embed,
        view=view
    )

    return message.id

async def create_application(request):
    api_key = request.headers.get("Authorization")
    if api_key != f"Bearer {BOT_API_KEY}":
        return web.json_response({"error":"Unauthorized"},status=401)
    try:
        data = await request.json()
        required_fields = [
            "applicationId",
            "discordId",
            "username",
            "age",
            "experience",
            "ic",
            "ooc"
        ]
        for field in required_fields:
            if field not in data:
                return web.json_response({"error": f"Missing field: {field}"},status=400)
        message_id = await send_whitelist_application(data)

        return web.json_response({
            "success": True,
            "messageId": str(message_id)
        })
    except Exception as error:
        print("Failed to create Discord application:", error)

        return web.json_response({
            "success": False,
            "error": str(error)
        }, status=500)

async def get_member_count(request):
    api_key = request.headers.get("Authorization")

    if api_key != f"Bearer {BOT_API_KEY}":
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response({
        "success": True,
        "memberCount": member_count
    })


async def start_api():
    app = web.Application()
    app.router.add_get("/api/member-count", get_member_count)
    app.router.add_post("/api/applications", create_application)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner,"127.0.0.1",4000)
    await site.start()
    print("Bot API running on http://127.0.0.1:4000")

@bot.tree.command(name="ping",description="Tarkista botin viive.")
async def ping(interaction:discord.Interaction):
    await interaction.response.send_message(f"Pong! Botin viive on {round(bot.latency) * 1000} ms", ephemeral=True)

@bot.tree.command(name="wl-history",description="Näyttää pelaajan wl-historian.")
async def wl_history(interaction:discord.Interaction,user:discord.Member):
    if not is_admin(interaction):
        await interaction.response.send_message("Sinä et voi tarkastella wl-historiaa.",ephemeral=True)
        return
    await show_application_history(interaction,str(user.id))

@bot.event
async def on_ready():
    global member_count

    print(f"Logged in as {bot.user}")
    print(f"Bot ID: {bot.user.id}")

    guild = bot.get_guild(GUILD_ID)

    if guild is None:
        print("Discord server not found!")
    else:
        member_count = guild.member_count
        print(f"Server: {guild.name}")
        print(f"Members: {member_count}")

    await start_api()
    await bot.tree.sync()

    await bot.change_presence(
        activity=discord.Game(
            name="discord.gg/avenuesuomi",
        )
    )

@bot.command(description="Sends the bot's latency.")
async def ping(ctx):
    await ctx.respond(f"Pong! Latency is {bot.latency}")

bot.run(TOKEN)