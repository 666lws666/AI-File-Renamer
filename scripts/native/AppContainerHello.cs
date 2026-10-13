using System;
using System.IO;
using System.Text;

internal static class AppContainerHello
{
    private static int Main(string[] args)
    {
        if (args.Length != 0)
        {
            return 2;
        }

        try
        {
            byte[] greeting = Encoding.ASCII.GetBytes(
                "{\"protocol\":\"xuxia-appcontainer-hello\",\"version\":1}\r\n");
            using (Stream stdout = Console.OpenStandardOutput())
            {
                stdout.Write(greeting, 0, greeting.Length);
                stdout.Flush();
            }
            return 0;
        }
        catch (IOException)
        {
            return 1;
        }
    }
}
