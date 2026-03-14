<?php

declare(strict_types=1);

interface Greetable
{
    public function greet(): string;
}

class Greeter implements Greetable
{
    public function greet(): string
    {
        return 'Hello, World!';
    }
}
